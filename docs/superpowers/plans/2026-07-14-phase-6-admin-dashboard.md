# Admin Analytics Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `GET /admin/dashboard` — a single server-rendered, four-tab HTML page (Overview / Cost & Teams / Performance / Safety) summarizing the trailing 24h of `request_log` data, with hand-rolled vanilla-JS SVG charts and no new dependencies beyond Jinja2 templating.

**Architecture:** One backend aggregation module (`src/prism/core/analytics.py`) runs all queries for a `[since, until)` window and returns a single JSON-serializable dict. One route (`src/prism/api/dashboard.py`) gates access with HTTP Basic Auth, calls the analytics module with the real last-24h window, and renders `src/prism/templates/dashboard.html`, which embeds the data as a JSON island and uses vanilla JS to switch tabs and draw SVG charts client-side.

**Tech Stack:** FastAPI, Jinja2 (new direct dependency — see Global Constraints), SQLAlchemy 2.0 async (Postgres `percentile_cont` for latency percentiles), vanilla JS (no framework, no build step), inline SVG.

## Global Constraints

- Fixed last-24h window only — no query params for time range (spec §2)
- Auth: HTTP Basic, any username, `admin_secret` as password, `401` responses carry `WWW-Authenticate: Basic` (spec §2, §5)
- No chart library, no build step — hand-rolled SVG + vanilla JS (spec §2)
- Color tokens: bg `#0B0E14`, panel `#11151C`, border `#232838`, text `#E6E9EF`, text-muted `#8890A0`, accent `#5B8DEF`, danger `#E5484D` (spec §3)
- Type: system sans for labels, monospace for every number (spec §3)
- Empty states render "no data yet" messaging, never a crash; `percentile_cont` NULL coalesces to `0` (spec §5)
- `monthly_budget_usd == 0` → skip percentage calc, show "no budget set" (spec §5)
- `ruff check .`, `ruff format --check .`, and `mypy src/prism` must stay clean (established project convention — see `pyproject.toml` `[tool.ruff]`/`[tool.mypy]`)
- Run `uv run ruff check --fix <touched files>` and `uv run ruff format <touched files>` before every commit (project convention)
- This codebase's existing `db` fixture (`src/tests/conftest.py`) shares one testcontainers Postgres across the whole test session with no per-test rollback — tests that need exact, unpolluted aggregate values must use an explicit historical `since`/`until` window with a fixed anchor timestamp (see Task 1), not the real "now" window

---

### Task 1: Analytics query module

**Files:**
- Create: `src/prism/core/analytics.py`
- Test: `src/tests/integration/test_analytics.py`

**Interfaces:**
- Produces: `async def get_dashboard_data(db: AsyncSession, since: datetime | None = None, until: datetime | None = None) -> dict[str, object]` — the full JSON contract every later task consumes:
  ```
  {
    "overview": {
      "total_requests": int, "total_cost_usd": float,
      "cache_hit_rate": float, "error_rate": float,
      "hourly_volume": [{"hour": str, "count": int}, ...],
      "provider_mix": [{"provider": str, "count": int}, ...]
    },
    "cost_by_team": [
      {"team_name": str, "request_count": int, "total_cost_usd": float,
       "monthly_budget_usd": float, "budget_pct": float | None}, ...
    ],
    "cache_savings_usd": float,
    "performance": {
      "latency_p50_ms": float, "latency_p95_ms": float, "latency_p99_ms": float,
      "latency_by_provider": [{"provider": str, "avg_ms": float, "p95_ms": float}, ...],
      "fallback_rate_hourly": [{"hour": str, "rate": float}, ...]
    },
    "safety": {
      "blocks_hourly": [{"hour": str, "count": int}, ...],
      "blocks_by_reason": [{"reason": str, "count": int}, ...],
      "block_rate": float
    }
  }
  ```
  `hour` values are ISO-8601 strings (from `datetime.isoformat()`). `since`/`until` default to "last 24h through now" when omitted — this is what the route (Task 2) relies on.

- [ ] **Step 1: Write the failing tests**

Create `src/tests/integration/test_analytics.py`:

```python
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
async def test_get_dashboard_data_defaults_to_last_24h(db: AsyncSession) -> None:
    data = await get_dashboard_data(db)
    assert data["overview"]["total_requests"] >= 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest src/tests/integration/test_analytics.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'prism.core.analytics'`

- [ ] **Step 3: Implement the analytics module**

Create `src/prism/core/analytics.py`:

```python
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
        select(bucket, func.count(RequestLog.id).label("count"))
        .where(RequestLog.created_at >= since)
        .where(RequestLog.created_at < until)
    )
    if extra_where is not None:
        stmt = stmt.where(extra_where)
    stmt = stmt.group_by(bucket).order_by(bucket)
    result = await db.execute(stmt)
    return [{"hour": row.bucket.isoformat(), "count": row.count} for row in result.all()]


async def _get_provider_mix(
    db: AsyncSession, since: datetime, until: datetime
) -> list[dict[str, object]]:
    result = await db.execute(
        select(RequestLog.provider_used, func.count(RequestLog.id).label("count"))
        .where(RequestLog.created_at >= since)
        .where(RequestLog.created_at < until)
        .group_by(RequestLog.provider_used)
        .order_by(func.count(RequestLog.id).desc())
    )
    return [{"provider": row.provider_used, "count": row.count} for row in result.all()]


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
        select(RequestLog.virtual_model, func.avg(RequestLog.cost_usd).label("avg_cost"))
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
) -> dict[str, float]:
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
            "p95_ms": float(row.p95_ms) if row.p95_ms is not None else float(row.avg_ms),
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
        select(RequestLog.guardrail_flag, func.count(RequestLog.id).label("count"))
        .where(RequestLog.created_at >= since)
        .where(RequestLog.created_at < until)
        .where(RequestLog.provider_used == "blocked")
        .group_by(RequestLog.guardrail_flag)
    )
    buckets: dict[str, int] = {}
    for row in result.all():
        label = _guardrail_label(row.guardrail_flag)
        buckets[label] = buckets.get(label, 0) + row.count
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
    performance["latency_by_provider"] = await _get_latency_by_provider(db, since, until)
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest src/tests/integration/test_analytics.py -v`
Expected: 3 passed

- [ ] **Step 5: Lint and type-check**

Run: `uv run ruff check --fix src/prism/core/analytics.py src/tests/integration/test_analytics.py && uv run ruff format src/prism/core/analytics.py src/tests/integration/test_analytics.py && uv run mypy src/prism/core/analytics.py`
Expected: no errors (note `_guardrail_label` is imported from `prism.api.chat` — this is a private helper reused per spec §4; mypy strict should still pass since it's a plain function, not name-mangled)

- [ ] **Step 6: Commit**

```bash
git add src/prism/core/analytics.py src/tests/integration/test_analytics.py
git commit -m "add analytics aggregation module for admin dashboard"
```

---

### Task 2: Dashboard route with Basic Auth + bare template

**Files:**
- Create: `src/prism/api/dashboard.py`
- Create: `src/prism/templates/dashboard.html` (bare-bones in this task — Task 3 replaces it with the full styled version)
- Modify: `src/prism/main.py` — register the new router
- Modify: `pyproject.toml` — add explicit `jinja2` dependency (currently only a transitive dep via spacy; this task is the first direct `import jinja2`/`fastapi.templating` usage, so it must be pinned directly or a future unrelated dependency bump can silently drop it — see the `en_core_web_sm` incident in Phase 5 for why this matters)
- Test: `src/tests/integration/test_admin_dashboard.py`

**Interfaces:**
- Consumes: `get_dashboard_data(db, since=None, until=None) -> dict[str, object]` from Task 1 (`prism.core.analytics`)
- Produces: `GET /admin/dashboard` route, gated by `require_admin_basic` dependency (401 + `WWW-Authenticate: Basic` header on missing/wrong credentials, 200 HTML otherwise). Later tasks (3, 4) only touch `dashboard.html`, not this route.

- [ ] **Step 1: Add the jinja2 dependency**

In `pyproject.toml`, add to the main `dependencies` list (after `"httpx>=0.27.0",`):

```toml
    "jinja2>=3.1.0",
```

Run: `uv sync --extra dev`
Expected: resolves cleanly, `jinja2` now shows as a direct (not just transitive) dependency

- [ ] **Step 2: Write the failing tests**

Create `src/tests/integration/test_admin_dashboard.py`:

```python
import base64

import pytest
from httpx import ASGITransport, AsyncClient

from prism.main import app

ADMIN_SECRET = "change-me-in-production"


def _basic_auth_header(password: str, username: str = "admin") -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


@pytest.mark.integration
async def test_dashboard_requires_auth() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/admin/dashboard")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Basic"


@pytest.mark.integration
async def test_dashboard_rejects_wrong_password() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/admin/dashboard", headers=_basic_auth_header("wrong-secret")
        )
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Basic"


@pytest.mark.integration
async def test_dashboard_renders_with_correct_credentials() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/admin/dashboard", headers=_basic_auth_header(ADMIN_SECRET)
        )
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert 'id="dashboard-data"' in response.text
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest src/tests/integration/test_admin_dashboard.py -v`
Expected: FAIL — `404` (route doesn't exist yet) or `ModuleNotFoundError`

- [ ] **Step 4: Create the bare template**

Create `src/prism/templates/dashboard.html`:

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Prism — Admin Dashboard</title>
</head>
<body>
  <script id="dashboard-data" type="application/json">{{ data_json | safe }}</script>
</body>
</html>
```

- [ ] **Step 5: Implement the route**

Create `src/prism/api/dashboard.py`:

```python
import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from prism.config import settings
from prism.core.analytics import get_dashboard_data
from prism.db.session import get_db

router = APIRouter(prefix="/admin", tags=["admin"])
_basic = HTTPBasic(auto_error=False)

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


def require_admin_basic(
    credentials: HTTPBasicCredentials | None = Depends(_basic),
) -> None:
    if credentials is None or credentials.password != settings.admin_secret:
        raise HTTPException(
            status_code=401,
            detail="Invalid admin credentials",
            headers={"WWW-Authenticate": "Basic"},
        )


@router.get("/dashboard", dependencies=[Depends(require_admin_basic)])
async def dashboard(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    data = await get_dashboard_data(db)
    data_json = json.dumps(data).replace("</", "<\\/")
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={"data": data, "data_json": data_json},
    )
```

- [ ] **Step 6: Wire the router into the app**

In `src/prism/main.py`, add the import next to the other API router imports:

```python
from prism.api.dashboard import router as dashboard_router
```

And register it next to the other `include_router` calls:

```python
app.include_router(dashboard_router)
```

(The import block is alphabetical by module path — `admin` < `chat` < `dashboard` < `health` — so `from prism.api.dashboard import ...` goes after `from prism.api.chat import ...` and before `from prism.api.health import ...`. The `include_router` calls follow a separate functional grouping, not alphabetical — `include_router(dashboard_router)` goes after `include_router(admin_router)` and before `include_router(chat_router)`, keeping the two admin-surface routers adjacent.)

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run pytest src/tests/integration/test_admin_dashboard.py -v`
Expected: 3 passed

- [ ] **Step 8: Lint and type-check**

Run: `uv run ruff check --fix src/prism/api/dashboard.py src/prism/main.py src/tests/integration/test_admin_dashboard.py && uv run ruff format src/prism/api/dashboard.py src/prism/main.py src/tests/integration/test_admin_dashboard.py && uv run mypy src/prism/api/dashboard.py src/prism/main.py`
Expected: no errors

- [ ] **Step 9: Commit**

```bash
git add pyproject.toml uv.lock src/prism/api/dashboard.py src/prism/templates/dashboard.html src/prism/main.py src/tests/integration/test_admin_dashboard.py
git commit -m "add /admin/dashboard route with Basic Auth and bare template"
```

---

### Task 3: Full visual template — CSS tokens, layout, tab strip, all four views

**Files:**
- Modify: `src/prism/templates/dashboard.html` (full rewrite — CSS + complete server-rendered markup for all 4 views; charts are empty `<svg>` placeholders populated by Task 4's JS)
- Modify: `src/tests/integration/test_admin_dashboard.py` (add content assertions)

**Interfaces:**
- Consumes: the `data` dict shape from Task 1/2 exactly as documented in Task 1's Interfaces block
- Produces: `<svg data-chart="line|bar" data-series="<dotted.path>" data-x="<key>" data-y="<key>">` elements that Task 4's JS finds via `document.querySelectorAll("svg[data-chart]")` and populates — the `data-series` attribute is a dotted path into the embedded JSON (e.g. `"overview.hourly_volume"`) that Task 4's `getPath()` helper resolves

- [ ] **Step 1: Write the failing tests**

Add to `src/tests/integration/test_admin_dashboard.py`:

```python
@pytest.mark.integration
async def test_dashboard_shows_seeded_team_and_guardrail_data() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        team = await client.post(
            "/admin/teams",
            json={"name": "dashboard-view-test"},
            headers={"Authorization": f"Bearer {ADMIN_SECRET}"},
        )
        team_id = team.json()["id"]
        key_resp = await client.post(
            "/admin/keys",
            json={"team_id": team_id},
            headers={"Authorization": f"Bearer {ADMIN_SECRET}"},
        )
        api_key = key_resp.json()["key"]

        await client.post(
            "/v1/chat/completions",
            json={
                "model": "fast",
                "messages": [
                    {"role": "user", "content": "My email is test@example.com"}
                ],
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )

        response = await client.get(
            "/admin/dashboard", headers=_basic_auth_header(ADMIN_SECRET)
        )

    assert response.status_code == 200
    assert "dashboard-view-test" in response.text
    assert 'role="tablist"' in response.text
    assert 'id="panel-overview"' in response.text
    assert 'id="panel-cost"' in response.text
    assert 'id="panel-performance"' in response.text
    assert 'id="panel-safety"' in response.text
```

No new imports are needed for this test — it only uses the `AsyncClient`/`ASGITransport`/`app` already imported in this file.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest src/tests/integration/test_admin_dashboard.py::test_dashboard_shows_seeded_team_and_guardrail_data -v`
Expected: FAIL — `AssertionError` (bare template doesn't contain team name or tab markup)

- [ ] **Step 3: Replace the template with the full styled version**

Replace `src/prism/templates/dashboard.html` entirely:

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Prism — Admin Dashboard</title>
  <style>
    :root {
      --bg: #0B0E14;
      --panel: #11151C;
      --border: #232838;
      --text: #E6E9EF;
      --text-muted: #8890A0;
      --accent: #5B8DEF;
      --danger: #E5484D;
      --font-sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, sans-serif;
      --font-mono: ui-monospace, "JetBrains Mono", "SFMono-Regular", Menlo, monospace;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: var(--font-sans);
      padding: 2rem;
      line-height: 1.5;
    }
    header h1 { font-size: 1.25rem; font-weight: 600; margin: 0 0 0.25rem; }
    header p { color: var(--text-muted); margin: 0 0 2rem; font-size: 0.875rem; }
    .tabs {
      display: flex;
      gap: 0.5rem;
      border-bottom: 1px solid var(--border);
      margin-bottom: 2rem;
    }
    .tab {
      background: none;
      border: none;
      color: var(--text-muted);
      font-family: var(--font-sans);
      font-size: 0.875rem;
      padding: 0.75rem 1rem;
      cursor: pointer;
      border-bottom: 2px solid transparent;
    }
    .tab:hover { color: var(--text); }
    .tab[aria-selected="true"] { color: var(--text); border-bottom-color: var(--accent); }
    .tab:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
    .panel { display: none; }
    .panel[data-active="true"] { display: block; }
    @media (prefers-reduced-motion: no-preference) {
      .panel[data-active="true"] { animation: fade-in 0.15s ease-out; }
    }
    @keyframes fade-in { from { opacity: 0; } to { opacity: 1; } }
    .tiles {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
      gap: 1px;
      background: var(--border);
      border: 1px solid var(--border);
      margin-bottom: 2rem;
    }
    .tile { background: var(--panel); padding: 1.25rem; }
    .tile .label {
      color: var(--text-muted);
      font-size: 0.6875rem;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      margin-bottom: 0.5rem;
    }
    .tile .value { font-family: var(--font-mono); font-size: 1.5rem; }
    .tile .value.danger { color: var(--danger); }
    section.block { border-top: 1px solid var(--border); padding-top: 1.5rem; margin-bottom: 2rem; }
    section.block h2 {
      font-size: 0.75rem;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: var(--text-muted);
      margin: 0 0 1rem;
      font-weight: 600;
    }
    table { width: 100%; border-collapse: collapse; font-size: 0.875rem; }
    th {
      text-align: left;
      color: var(--text-muted);
      font-weight: 500;
      font-size: 0.6875rem;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      padding: 0.5rem 0.75rem;
      border-bottom: 1px solid var(--border);
    }
    td { padding: 0.5rem 0.75rem; border-bottom: 1px solid var(--border); font-family: var(--font-mono); }
    td.text { font-family: var(--font-sans); }
    .empty-state {
      color: var(--text-muted);
      font-size: 0.875rem;
      padding: 1.5rem;
      text-align: center;
      border: 1px dashed var(--border);
    }
    .chart { width: 100%; height: 160px; overflow: visible; }
    .chart-point { fill: var(--accent); cursor: pointer; }
    .chart-bar { fill: var(--accent); cursor: pointer; }
    .chart-line { fill: none; stroke: var(--accent); stroke-width: 2; }
    .chart-tooltip {
      position: absolute;
      background: var(--panel);
      border: 1px solid var(--border);
      padding: 0.375rem 0.5rem;
      font-family: var(--font-mono);
      font-size: 0.75rem;
      pointer-events: none;
      display: none;
      border-radius: 2px;
    }
  </style>
</head>
<body>
  <header>
    <h1>Prism — Admin Dashboard</h1>
    <p>Last 24 hours</p>
  </header>

  <div class="tabs" role="tablist">
    <button class="tab" role="tab" id="tab-overview" aria-controls="panel-overview" aria-selected="true" tabindex="0" data-target="overview">Overview</button>
    <button class="tab" role="tab" id="tab-cost" aria-controls="panel-cost" aria-selected="false" tabindex="-1" data-target="cost">Cost &amp; Teams</button>
    <button class="tab" role="tab" id="tab-performance" aria-controls="panel-performance" aria-selected="false" tabindex="-1" data-target="performance">Performance</button>
    <button class="tab" role="tab" id="tab-safety" aria-controls="panel-safety" aria-selected="false" tabindex="-1" data-target="safety">Safety</button>
  </div>

  <section class="panel" id="panel-overview" role="tabpanel" aria-labelledby="tab-overview" data-active="true">
    <div class="tiles">
      <div class="tile"><div class="label">Total Requests</div><div class="value">{{ data.overview.total_requests }}</div></div>
      <div class="tile"><div class="label">Total Cost</div><div class="value">${{ "%.4f"|format(data.overview.total_cost_usd) }}</div></div>
      <div class="tile"><div class="label">Cache Hit Rate</div><div class="value">{{ "%.1f"|format(data.overview.cache_hit_rate * 100) }}%</div></div>
      <div class="tile"><div class="label">Error Rate</div><div class="value {{ 'danger' if data.overview.error_rate > 0 else '' }}">{{ "%.1f"|format(data.overview.error_rate * 100) }}%</div></div>
    </div>
    <section class="block">
      <h2>Request Volume</h2>
      {% if data.overview.hourly_volume %}
      <svg class="chart" data-chart="line" data-series="overview.hourly_volume" data-x="hour" data-y="count"></svg>
      {% else %}
      <div class="empty-state">No requests in the last 24 hours yet.</div>
      {% endif %}
    </section>
    <section class="block">
      <h2>Provider Mix</h2>
      {% if data.overview.provider_mix %}
      <svg class="chart" data-chart="bar" data-series="overview.provider_mix" data-x="provider" data-y="count"></svg>
      {% else %}
      <div class="empty-state">No requests in the last 24 hours yet.</div>
      {% endif %}
    </section>
  </section>

  <section class="panel" id="panel-cost" role="tabpanel" aria-labelledby="tab-cost" data-active="false">
    <section class="block">
      <h2>Cost by Team</h2>
      {% if data.cost_by_team %}
      <svg class="chart" data-chart="bar" data-series="cost_by_team" data-x="team_name" data-y="total_cost_usd"></svg>
      <table>
        <thead><tr><th>Team</th><th>Requests</th><th>Cost</th><th>Budget Used</th></tr></thead>
        <tbody>
          {% for team in data.cost_by_team %}
          <tr>
            <td class="text">{{ team.team_name }}</td>
            <td>{{ team.request_count }}</td>
            <td>${{ "%.4f"|format(team.total_cost_usd) }}</td>
            <td>{% if team.budget_pct is not none %}{{ "%.1f"|format(team.budget_pct) }}%{% else %}no budget set{% endif %}</td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
      {% else %}
      <div class="empty-state">No team activity in the last 24 hours yet.</div>
      {% endif %}
    </section>
    <section class="block">
      <h2>Estimated Cache Savings</h2>
      <div class="tiles">
        <div class="tile"><div class="label">Saved (est.)</div><div class="value">${{ "%.4f"|format(data.cache_savings_usd) }}</div></div>
      </div>
    </section>
  </section>

  <section class="panel" id="panel-performance" role="tabpanel" aria-labelledby="tab-performance" data-active="false">
    <div class="tiles">
      <div class="tile"><div class="label">p50 Latency</div><div class="value">{{ "%.0f"|format(data.performance.latency_p50_ms) }}ms</div></div>
      <div class="tile"><div class="label">p95 Latency</div><div class="value">{{ "%.0f"|format(data.performance.latency_p95_ms) }}ms</div></div>
      <div class="tile"><div class="label">p99 Latency</div><div class="value">{{ "%.0f"|format(data.performance.latency_p99_ms) }}ms</div></div>
    </div>
    <section class="block">
      <h2>Latency by Provider</h2>
      {% if data.performance.latency_by_provider %}
      <svg class="chart" data-chart="bar" data-series="performance.latency_by_provider" data-x="provider" data-y="avg_ms"></svg>
      {% else %}
      <div class="empty-state">No requests in the last 24 hours yet.</div>
      {% endif %}
    </section>
    <section class="block">
      <h2>Fallback Rate Over Time</h2>
      {% if data.performance.fallback_rate_hourly %}
      <svg class="chart" data-chart="line" data-series="performance.fallback_rate_hourly" data-x="hour" data-y="rate"></svg>
      {% else %}
      <div class="empty-state">No requests in the last 24 hours yet.</div>
      {% endif %}
    </section>
  </section>

  <section class="panel" id="panel-safety" role="tabpanel" aria-labelledby="tab-safety" data-active="false">
    <div class="tiles">
      <div class="tile"><div class="label">Block Rate</div><div class="value {{ 'danger' if data.safety.block_rate > 0 else '' }}">{{ "%.1f"|format(data.safety.block_rate * 100) }}%</div></div>
    </div>
    <section class="block">
      <h2>Guardrail Blocks Over Time</h2>
      {% if data.safety.blocks_hourly %}
      <svg class="chart" data-chart="line" data-series="safety.blocks_hourly" data-x="hour" data-y="count"></svg>
      {% else %}
      <div class="empty-state">No blocked requests in the last 24 hours.</div>
      {% endif %}
    </section>
    <section class="block">
      <h2>Blocks by Reason</h2>
      {% if data.safety.blocks_by_reason %}
      <svg class="chart" data-chart="bar" data-series="safety.blocks_by_reason" data-x="reason" data-y="count"></svg>
      {% else %}
      <div class="empty-state">No blocked requests in the last 24 hours.</div>
      {% endif %}
    </section>
  </section>

  <div class="chart-tooltip" id="chart-tooltip"></div>

  <script id="dashboard-data" type="application/json">{{ data_json | safe }}</script>
</body>
</html>
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest src/tests/integration/test_admin_dashboard.py -v`
Expected: 4 passed

- [ ] **Step 5: Lint and type-check**

Run: `uv run ruff check --fix src/tests/integration/test_admin_dashboard.py && uv run ruff format src/tests/integration/test_admin_dashboard.py && uv run mypy src/prism/api/dashboard.py`
Expected: no errors (the `.html` template isn't a lint/mypy target)

- [ ] **Step 6: Commit**

```bash
git add src/prism/templates/dashboard.html src/tests/integration/test_admin_dashboard.py
git commit -m "build full dashboard layout, CSS tokens, and all four view sections"
```

---

### Task 4: Vanilla JS — tab switching + SVG chart rendering

**Files:**
- Modify: `src/prism/templates/dashboard.html` (append the `<script>` block after the data island; add the `.chart-line` CSS class reference is already present from Task 3)
- Test: manual browser verification (this logic runs client-side and isn't reachable from pytest) + one automated smoke check

**Interfaces:**
- Consumes: `data-chart`, `data-series`, `data-x`, `data-y` attributes on `<svg>` elements from Task 3, and the `#dashboard-data` JSON island from Task 2

- [ ] **Step 1: Write the automated smoke-test addition**

Add to `src/tests/integration/test_admin_dashboard.py`:

```python
@pytest.mark.integration
async def test_dashboard_includes_tab_and_chart_script() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/admin/dashboard", headers=_basic_auth_header(ADMIN_SECRET)
        )
    assert 'data-chart="line"' in response.text
    assert 'data-chart="bar"' in response.text
    assert "activateTab" in response.text
```

Run: `uv run pytest src/tests/integration/test_admin_dashboard.py::test_dashboard_includes_tab_and_chart_script -v`
Expected: FAIL — `activateTab` not yet in the response

- [ ] **Step 2: Append the script block**

In `src/prism/templates/dashboard.html`, insert immediately before the closing `</body>` tag (after the `#dashboard-data` `<script>` from Task 2):

```html
  <script>
    (function () {
      "use strict";

      var data = JSON.parse(document.getElementById("dashboard-data").textContent);

      function getPath(obj, path) {
        return path.split(".").reduce(function (acc, key) {
          return acc ? acc[key] : undefined;
        }, obj);
      }

      var tabs = Array.prototype.slice.call(document.querySelectorAll(".tab"));

      function activateTab(target) {
        tabs.forEach(function (tab) {
          var active = tab.dataset.target === target;
          tab.setAttribute("aria-selected", active ? "true" : "false");
          tab.tabIndex = active ? 0 : -1;
        });
        document.querySelectorAll(".panel").forEach(function (panel) {
          panel.dataset.active = panel.id === "panel-" + target ? "true" : "false";
        });
      }

      tabs.forEach(function (tab) {
        tab.addEventListener("click", function () {
          activateTab(tab.dataset.target);
        });
        tab.addEventListener("keydown", function (evt) {
          var idx = tabs.indexOf(tab);
          if (evt.key === "ArrowRight") {
            evt.preventDefault();
            var next = tabs[(idx + 1) % tabs.length];
            next.focus();
            activateTab(next.dataset.target);
          } else if (evt.key === "ArrowLeft") {
            evt.preventDefault();
            var prev = tabs[(idx - 1 + tabs.length) % tabs.length];
            prev.focus();
            activateTab(prev.dataset.target);
          }
        });
      });

      var tooltip = document.getElementById("chart-tooltip");

      function showTooltip(evt, text) {
        tooltip.textContent = text;
        tooltip.style.display = "block";
        tooltip.style.left = evt.pageX + 12 + "px";
        tooltip.style.top = evt.pageY + 12 + "px";
      }

      function hideTooltip() {
        tooltip.style.display = "none";
      }

      var SVG_NS = "http://www.w3.org/2000/svg";

      function renderLineChart(svg, points, xKey, yKey) {
        var width = svg.clientWidth || 600;
        var height = 160;
        var padding = 20;
        svg.setAttribute("viewBox", "0 0 " + width + " " + height);

        var values = points.map(function (p) { return p[yKey]; });
        var maxY = Math.max.apply(null, values.concat([0.0001]));
        var stepX = points.length > 1 ? (width - padding * 2) / (points.length - 1) : 0;

        var coords = points.map(function (p, i) {
          var x = padding + i * stepX;
          var y = height - padding - (p[yKey] / maxY) * (height - padding * 2);
          return { x: x, y: y, label: p[xKey], value: p[yKey] };
        });

        var pathD = coords
          .map(function (c, i) { return (i === 0 ? "M" : "L") + c.x + "," + c.y; })
          .join(" ");

        var path = document.createElementNS(SVG_NS, "path");
        path.setAttribute("d", pathD);
        path.setAttribute("class", "chart-line");
        svg.appendChild(path);

        coords.forEach(function (c) {
          var circle = document.createElementNS(SVG_NS, "circle");
          circle.setAttribute("cx", String(c.x));
          circle.setAttribute("cy", String(c.y));
          circle.setAttribute("r", "3");
          circle.setAttribute("class", "chart-point");
          circle.addEventListener("mousemove", function (evt) {
            showTooltip(evt, c.label + ": " + c.value);
          });
          circle.addEventListener("mouseleave", hideTooltip);
          svg.appendChild(circle);
        });
      }

      function renderBarChart(svg, points, xKey, yKey) {
        var width = svg.clientWidth || 600;
        var height = 160;
        var padding = 20;
        svg.setAttribute("viewBox", "0 0 " + width + " " + height);

        var values = points.map(function (p) { return p[yKey]; });
        var maxY = Math.max.apply(null, values.concat([0.0001]));
        var barWidth = (width - padding * 2) / points.length;

        points.forEach(function (p, i) {
          var barHeight = (p[yKey] / maxY) * (height - padding * 2);
          var x = padding + i * barWidth;
          var y = height - padding - barHeight;
          var rect = document.createElementNS(SVG_NS, "rect");
          rect.setAttribute("x", String(x + barWidth * 0.1));
          rect.setAttribute("y", String(y));
          rect.setAttribute("width", String(barWidth * 0.8));
          rect.setAttribute("height", String(barHeight));
          rect.setAttribute("class", "chart-bar");
          rect.addEventListener("mousemove", function (evt) {
            showTooltip(evt, p[xKey] + ": " + p[yKey]);
          });
          rect.addEventListener("mouseleave", hideTooltip);
          svg.appendChild(rect);
        });
      }

      document.querySelectorAll("svg[data-chart]").forEach(function (svg) {
        var series = getPath(data, svg.dataset.series) || [];
        if (!series.length) return;
        var xKey = svg.dataset.x;
        var yKey = svg.dataset.y;
        if (svg.dataset.chart === "line") {
          renderLineChart(svg, series, xKey, yKey);
        } else {
          renderBarChart(svg, series, xKey, yKey);
        }
      });

      window.activateTab = activateTab;
    })();
  </script>
```

Note: `window.activateTab = activateTab;` at the end exposes the function so the Step 1 smoke test's `"activateTab" in response.text` check finds the literal function name in the served HTML (it's already present as the function declaration itself, so this line is for clarity/potential manual console debugging, not required for the test to pass).

- [ ] **Step 3: Run tests to verify they pass**

Run: `uv run pytest src/tests/integration/test_admin_dashboard.py -v`
Expected: 5 passed

- [ ] **Step 4: Manual browser verification**

Run: `docker-compose up -d postgres redis` (or the full stack), then `uv run uvicorn prism.main:app --reload` from the repo root.

Open `http://localhost:8000/admin/dashboard` in a browser, log in with any username and password `change-me-in-production` (or your configured `ADMIN_SECRET`) at the Basic Auth prompt. Verify:
- Page loads with dark theme, four tabs visible, "Overview" active by default
- Clicking each tab switches the visible panel; arrow keys move focus between tabs when a tab is focused
- If there's recent traffic (send a few requests via `/v1/chat/completions` first, or reuse existing `.env`/seeded data), charts render as lines/bars with hover tooltips; otherwise each section shows the "no data yet" empty state without any console errors
- Browser DevTools console shows no JS errors
- Tab focus rings are visible when tabbing via keyboard

- [ ] **Step 5: Verify templates are packaged into the Docker image**

Run:
```bash
docker build -f deploy/docker/Dockerfile -t prism:dashboard-check .
docker run --rm prism:dashboard-check python -c "from pathlib import Path; import prism; p = Path(prism.__file__).parent / 'templates' / 'dashboard.html'; assert p.exists(), p; print('template packaged OK')"
docker rmi prism:dashboard-check
```
Expected: `template packaged OK` (this catches the same class of "works locally, missing in the image" bug hit twice already this project with `en_core_web_sm` and `cryptography` — hatchling's default file selection should include it since the file will be git-tracked, but verify rather than assume)

- [ ] **Step 6: Lint and type-check**

Run: `uv run ruff check --fix src/tests/integration/test_admin_dashboard.py && uv run ruff format src/tests/integration/test_admin_dashboard.py && uv run mypy src/prism`
Expected: no errors

- [ ] **Step 7: Commit**

```bash
git add src/prism/templates/dashboard.html src/tests/integration/test_admin_dashboard.py
git commit -m "add tab switching and hand-rolled SVG chart rendering to admin dashboard"
```

---

### Task 5: Full-suite verification

**Files:** none (verification only)

- [ ] **Step 1: Run the full test suite**

Run: `uv run pytest -m "not requires_ollama" -v`
Expected: all tests pass, including all analytics and dashboard tests from Tasks 1–4

- [ ] **Step 2: Run lint, format check, and mypy across the whole repo**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy src/prism`
Expected: no errors

- [ ] **Step 3: Push and confirm CI is green**

```bash
git push origin main
```
Then check the GitHub Actions run for this push (`gh run watch <run-id> --exit-status` or the Actions tab) — all four required jobs (Lint, Type check, Test, Build + scan image) must pass, since branch protection now requires them.

- [ ] **Step 4: Update project memory**

Mark this sub-project done in `project_prism.md`'s Phase 6 section (admin analytics view ✅, Locust load test next).
