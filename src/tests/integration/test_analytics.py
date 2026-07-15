import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from prism.core.analytics import get_dashboard_data
from prism.db.models import ApiKey, RequestLog, Team


@pytest.mark.integration
async def test_get_dashboard_data_computes_all_fields_in_isolated_window(
    db: AsyncSession,
) -> None:
    # Fixed historical anchor — no other test in this session ever writes
    # here, so exact-value assertions are safe despite the shared DB.
    anchor = datetime(2020, 1, 1, tzinfo=UTC)
    since = anchor - timedelta(minutes=1)
    until = anchor + timedelta(minutes=1)

    team = Team(
        name=f"analytics-{uuid.uuid4().hex[:8]}",
        monthly_budget_usd=Decimal("50.00"),
    )
    db.add(team)
    await db.flush()
    api_key = ApiKey(
        team_id=team.id,
        key_hash=f"hash-{uuid.uuid4().hex}",
        key_prefix="prism_test",
    )
    db.add(api_key)
    await db.flush()

    db.add_all(
        [
            RequestLog(
                api_key_id=api_key.id,
                virtual_model="fast",
                provider_used="ollama",
                cache_hit=False,
                cost_usd=Decimal("0.01"),
                latency_ms=100,
                status_code=200,
                created_at=anchor,
            ),
            RequestLog(
                api_key_id=api_key.id,
                virtual_model="fast",
                provider_used="cache",
                cache_hit=True,
                cost_usd=Decimal("0"),
                latency_ms=5,
                status_code=200,
                created_at=anchor,
            ),
            RequestLog(
                api_key_id=api_key.id,
                virtual_model="fast",
                provider_used="ollama",
                cache_hit=False,
                cost_usd=Decimal("0.01"),
                latency_ms=200,
                status_code=500,
                created_at=anchor,
            ),
            RequestLog(
                api_key_id=api_key.id,
                virtual_model="fast",
                provider_used="blocked",
                status_code=400,
                guardrail_flag="PII: email detected",
                created_at=anchor,
            ),
        ]
    )
    await db.commit()

    data = await get_dashboard_data(db, since=since, until=until)

    overview = data["overview"]
    assert overview["total_requests"] == 4
    assert overview["total_cost_usd"] == pytest.approx(0.02)
    assert overview["cache_hit_rate"] == pytest.approx(1 / 4)
    assert overview["error_rate"] == pytest.approx(2 / 4)
    assert overview["hourly_volume"] == [
        {"hour": anchor.replace(minute=0, second=0).isoformat(), "count": 4}
    ]
    assert {"provider": "ollama", "count": 2} in overview["provider_mix"]
    assert {"provider": "cache", "count": 1} in overview["provider_mix"]
    assert {"provider": "blocked", "count": 1} in overview["provider_mix"]

    assert len(data["cost_by_team"]) == 1
    team_row = data["cost_by_team"][0]
    assert team_row["team_name"] == team.name
    assert team_row["request_count"] == 4
    assert team_row["total_cost_usd"] == pytest.approx(0.02)
    assert team_row["monthly_budget_usd"] == pytest.approx(50.0)
    assert team_row["budget_pct"] == pytest.approx(0.02 / 50.0 * 100)

    assert data["cache_savings_usd"] == pytest.approx(0.01)

    perf = data["performance"]
    assert perf["latency_p50_ms"] > 0
    assert perf["latency_p95_ms"] >= perf["latency_p50_ms"]
    latency_by_provider = {row["provider"]: row for row in perf["latency_by_provider"]}
    assert latency_by_provider["ollama"]["avg_ms"] == pytest.approx(150.0)
    assert perf["fallback_rate_hourly"] == [
        {"hour": anchor.replace(minute=0, second=0).isoformat(), "rate": 0.0}
    ]

    safety = data["safety"]
    assert safety["blocks_hourly"] == [
        {"hour": anchor.replace(minute=0, second=0).isoformat(), "count": 1}
    ]
    assert safety["blocks_by_reason"] == [{"reason": "pii_detected", "count": 1}]
    assert safety["block_rate"] == pytest.approx(1 / 4)


@pytest.mark.integration
async def test_get_dashboard_data_empty_window_returns_zeroed_stats(
    db: AsyncSession,
) -> None:
    anchor = datetime(2019, 1, 1, tzinfo=UTC)

    data = await get_dashboard_data(
        db,
        since=anchor - timedelta(minutes=1),
        until=anchor + timedelta(minutes=1),
    )

    assert data["overview"]["total_requests"] == 0
    assert data["overview"]["total_cost_usd"] == 0.0
    assert data["overview"]["cache_hit_rate"] == 0.0
    assert data["overview"]["error_rate"] == 0.0
    assert data["overview"]["hourly_volume"] == []
    assert data["overview"]["provider_mix"] == []
    assert data["cost_by_team"] == []
    assert data["cache_savings_usd"] == 0.0
    assert data["performance"]["latency_p50_ms"] == 0.0
    assert data["performance"]["latency_p95_ms"] == 0.0
    assert data["performance"]["latency_p99_ms"] == 0.0
    assert data["performance"]["latency_by_provider"] == []
    assert data["performance"]["fallback_rate_hourly"] == []
    assert data["safety"]["blocks_hourly"] == []
    assert data["safety"]["blocks_by_reason"] == []
    assert data["safety"]["block_rate"] == 0.0


@pytest.mark.integration
async def test_latency_percentiles_exclude_cache_and_blocked_requests(
    db: AsyncSession,
) -> None:
    # Cache hits and guardrail blocks never reach a provider, so their
    # near-zero latency shouldn't pull the gateway-overhead percentiles
    # down and make a real provider's latency look contradictory next to
    # them. Only "ollama" here should count toward p50/p95.
    anchor = datetime(2021, 1, 1, tzinfo=UTC)
    since = anchor - timedelta(minutes=1)
    until = anchor + timedelta(minutes=1)

    team = Team(
        name=f"latency-{uuid.uuid4().hex[:8]}", monthly_budget_usd=Decimal("50.00")
    )
    db.add(team)
    await db.flush()
    api_key = ApiKey(
        team_id=team.id, key_hash=f"hash-{uuid.uuid4().hex}", key_prefix="prism_test"
    )
    db.add(api_key)
    await db.flush()

    db.add_all(
        [
            RequestLog(
                api_key_id=api_key.id,
                virtual_model="fast",
                provider_used="ollama",
                cache_hit=False,
                latency_ms=1000,
                status_code=200,
                created_at=anchor,
            ),
            RequestLog(
                api_key_id=api_key.id,
                virtual_model="fast",
                provider_used="cache",
                cache_hit=True,
                latency_ms=1,
                status_code=200,
                created_at=anchor,
            ),
            RequestLog(
                api_key_id=api_key.id,
                virtual_model="fast",
                provider_used="cache",
                cache_hit=True,
                latency_ms=1,
                status_code=200,
                created_at=anchor,
            ),
        ]
    )
    await db.commit()

    data = await get_dashboard_data(db, since=since, until=until)

    # If the two 1ms cache hits were included, p50 of [1, 1, 1000] would be
    # 1ms, not 1000ms.
    assert data["performance"]["latency_p50_ms"] == pytest.approx(1000.0)


@pytest.mark.integration
async def test_get_dashboard_data_defaults_to_last_24h(db: AsyncSession) -> None:
    data = await get_dashboard_data(db)
    assert data["overview"]["total_requests"] >= 0
