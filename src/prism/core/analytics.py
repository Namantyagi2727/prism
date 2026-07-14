from datetime import UTC, datetime, timedelta

from sqlalchemy import ColumnElement, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from prism.api.chat import _guardrail_label
from prism.db.models import ApiKey, RequestLog, Team


async def _get_overview(
    db: AsyncSession, since: datetime, until: datetime
) -> dict[str, object]:
    result = await db.execute(
        select(
            func.count(RequestLog.id).label("total"),
            func.coalesce(func.sum(RequestLog.cost_usd), 0).label("total_cost"),
            func.coalesce(
                func.sum(case((RequestLog.cache_hit.is_(True), 1), else_=0)), 0
            ).label("cache_hits"),
            func.coalesce(
                func.sum(case((RequestLog.status_code >= 400, 1), else_=0)), 0
            ).label("errors"),
        )
        .where(RequestLog.created_at >= since)
        .where(RequestLog.created_at < until)
    )
    row = result.one()
    total = row.total or 0
    return {
        "total_requests": total,
        "total_cost_usd": float(row.total_cost),
        "cache_hit_rate": (row.cache_hits / total) if total else 0.0,
        "error_rate": (row.errors / total) if total else 0.0,
    }


async def _get_hourly_bucketed_count(
    db: AsyncSession,
    since: datetime,
    until: datetime,
    extra_where: ColumnElement[bool] | None = None,
) -> list[dict[str, object]]:
    bucket = func.date_trunc("hour", RequestLog.created_at).label("bucket")
    stmt = (
        select(bucket, func.count(RequestLog.id).label("n"))
        .where(RequestLog.created_at >= since)
        .where(RequestLog.created_at < until)
    )
    if extra_where is not None:
        stmt = stmt.where(extra_where)
    stmt = stmt.group_by(bucket).order_by(bucket)
    result = await db.execute(stmt)
    return [{"hour": row.bucket.isoformat(), "count": row.n} for row in result.all()]


async def _get_provider_mix(
    db: AsyncSession, since: datetime, until: datetime
) -> list[dict[str, object]]:
    result = await db.execute(
        select(RequestLog.provider_used, func.count(RequestLog.id).label("n"))
        .where(RequestLog.created_at >= since)
        .where(RequestLog.created_at < until)
        .group_by(RequestLog.provider_used)
        .order_by(func.count(RequestLog.id).desc())
    )
    return [{"provider": row.provider_used, "count": row.n} for row in result.all()]


async def _get_cost_by_team(
    db: AsyncSession, since: datetime, until: datetime
) -> list[dict[str, object]]:
    result = await db.execute(
        select(
            Team.name,
            Team.monthly_budget_usd,
            func.count(RequestLog.id).label("request_count"),
            func.coalesce(func.sum(RequestLog.cost_usd), 0).label("total_cost"),
        )
        .select_from(Team)
        .join(ApiKey, ApiKey.team_id == Team.id)
        .join(RequestLog, RequestLog.api_key_id == ApiKey.id)
        .where(RequestLog.created_at >= since)
        .where(RequestLog.created_at < until)
        .group_by(Team.id, Team.name, Team.monthly_budget_usd)
        .order_by(func.sum(RequestLog.cost_usd).desc())
    )
    teams: list[dict[str, object]] = []
    for row in result.all():
        budget = float(row.monthly_budget_usd)
        total_cost = float(row.total_cost)
        budget_pct = (total_cost / budget * 100) if budget > 0 else None
        teams.append(
            {
                "team_name": row.name,
                "request_count": row.request_count,
                "total_cost_usd": total_cost,
                "monthly_budget_usd": budget,
                "budget_pct": budget_pct,
            }
        )
    return teams


async def _get_cache_savings(
    db: AsyncSession, since: datetime, until: datetime
) -> float:
    avg_cost_result = await db.execute(
        select(
            RequestLog.virtual_model, func.avg(RequestLog.cost_usd).label("avg_cost")
        )
        .where(RequestLog.created_at >= since)
        .where(RequestLog.created_at < until)
        .where(RequestLog.cache_hit.is_(False))
        .where(RequestLog.cost_usd.is_not(None))
        .group_by(RequestLog.virtual_model)
    )
    avg_cost_by_model = {
        row.virtual_model: float(row.avg_cost) for row in avg_cost_result.all()
    }

    hits_result = await db.execute(
        select(RequestLog.virtual_model, func.count(RequestLog.id).label("hits"))
        .where(RequestLog.created_at >= since)
        .where(RequestLog.created_at < until)
        .where(RequestLog.cache_hit.is_(True))
        .group_by(RequestLog.virtual_model)
    )
    savings = 0.0
    for row in hits_result.all():
        savings += avg_cost_by_model.get(row.virtual_model, 0.0) * row.hits
    return savings


async def _get_latency_percentiles(
    db: AsyncSession, since: datetime, until: datetime
) -> dict[str, object]:
    result = await db.execute(
        select(
            func.percentile_cont(0.5).within_group(RequestLog.latency_ms).label("p50"),
            func.percentile_cont(0.95).within_group(RequestLog.latency_ms).label("p95"),
            func.percentile_cont(0.99).within_group(RequestLog.latency_ms).label("p99"),
        )
        .where(RequestLog.created_at >= since)
        .where(RequestLog.created_at < until)
        .where(RequestLog.latency_ms.is_not(None))
    )
    row = result.one()
    return {
        "latency_p50_ms": float(row.p50) if row.p50 is not None else 0.0,
        "latency_p95_ms": float(row.p95) if row.p95 is not None else 0.0,
        "latency_p99_ms": float(row.p99) if row.p99 is not None else 0.0,
    }


async def _get_latency_by_provider(
    db: AsyncSession, since: datetime, until: datetime
) -> list[dict[str, object]]:
    result = await db.execute(
        select(
            RequestLog.provider_used,
            func.avg(RequestLog.latency_ms).label("avg_ms"),
            func.percentile_cont(0.95)
            .within_group(RequestLog.latency_ms)
            .label("p95_ms"),
        )
        .where(RequestLog.created_at >= since)
        .where(RequestLog.created_at < until)
        .where(RequestLog.latency_ms.is_not(None))
        .group_by(RequestLog.provider_used)
        .order_by(func.avg(RequestLog.latency_ms).desc())
    )
    return [
        {
            "provider": row.provider_used,
            "avg_ms": float(row.avg_ms),
            "p95_ms": float(row.p95_ms)
            if row.p95_ms is not None
            else float(row.avg_ms),
        }
        for row in result.all()
    ]


async def _get_fallback_rate_hourly(
    db: AsyncSession, since: datetime, until: datetime
) -> list[dict[str, object]]:
    bucket = func.date_trunc("hour", RequestLog.created_at).label("bucket")
    result = await db.execute(
        select(
            bucket,
            func.count(RequestLog.id).label("total"),
            func.coalesce(
                func.sum(case((RequestLog.fallback_triggered.is_(True), 1), else_=0)), 0
            ).label("fallbacks"),
        )
        .where(RequestLog.created_at >= since)
        .where(RequestLog.created_at < until)
        .group_by(bucket)
        .order_by(bucket)
    )
    return [
        {
            "hour": row.bucket.isoformat(),
            "rate": (row.fallbacks / row.total) if row.total else 0.0,
        }
        for row in result.all()
    ]


async def _get_blocks_by_reason(
    db: AsyncSession, since: datetime, until: datetime
) -> list[dict[str, object]]:
    result = await db.execute(
        select(RequestLog.guardrail_flag, func.count(RequestLog.id).label("n"))
        .where(RequestLog.created_at >= since)
        .where(RequestLog.created_at < until)
        .where(RequestLog.provider_used == "blocked")
        .group_by(RequestLog.guardrail_flag)
    )
    buckets: dict[str, int] = {}
    for row in result.all():
        label = _guardrail_label(row.guardrail_flag)
        buckets[label] = buckets.get(label, 0) + row.n
    return [
        {"reason": reason, "count": count}
        for reason, count in sorted(buckets.items(), key=lambda item: -item[1])
    ]


async def _get_block_rate(db: AsyncSession, since: datetime, until: datetime) -> float:
    result = await db.execute(
        select(
            func.count(RequestLog.id).label("total"),
            func.coalesce(
                func.sum(case((RequestLog.provider_used == "blocked", 1), else_=0)), 0
            ).label("blocked"),
        )
        .where(RequestLog.created_at >= since)
        .where(RequestLog.created_at < until)
    )
    row = result.one()
    total = row.total or 0
    return (row.blocked / total) if total else 0.0


async def get_dashboard_data(
    db: AsyncSession,
    since: datetime | None = None,
    until: datetime | None = None,
) -> dict[str, object]:
    now = datetime.now(UTC)
    if until is None:
        until = now
    if since is None:
        since = now - timedelta(hours=24)

    overview = await _get_overview(db, since, until)
    overview["hourly_volume"] = await _get_hourly_bucketed_count(db, since, until)
    overview["provider_mix"] = await _get_provider_mix(db, since, until)

    performance = await _get_latency_percentiles(db, since, until)
    performance["latency_by_provider"] = await _get_latency_by_provider(
        db, since, until
    )
    performance["fallback_rate_hourly"] = await _get_fallback_rate_hourly(
        db, since, until
    )

    safety = {
        "blocks_hourly": await _get_hourly_bucketed_count(
            db, since, until, extra_where=RequestLog.provider_used == "blocked"
        ),
        "blocks_by_reason": await _get_blocks_by_reason(db, since, until),
        "block_rate": await _get_block_rate(db, since, until),
    }

    return {
        "overview": overview,
        "cost_by_team": await _get_cost_by_team(db, since, until),
        "cache_savings_usd": await _get_cache_savings(db, since, until),
        "performance": performance,
        "safety": safety,
    }
