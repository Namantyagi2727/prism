# Phase 4 — Observability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add OpenTelemetry tracing, Prometheus metrics, and a live Grafana dashboard to Prism so request latency, cost, cache hit rate, and circuit-breaker state are visible in real time.

**Architecture:** Custom `prometheus_client` metrics are defined in `src/prism/observability/metrics.py` and recorded inside `chat.py` and `router.py`; a `/metrics` ASGI endpoint exposes them to Prometheus. OTel auto-instrumentation wraps every FastAPI request in a trace span and exports to Jaeger via OTLP/HTTP. Prometheus, Grafana, and Jaeger run as Docker Compose services; Grafana loads a provisioned dashboard on first boot.

**Tech Stack:** `opentelemetry-sdk`, `opentelemetry-instrumentation-fastapi`, `opentelemetry-exporter-otlp-proto-http`, `prometheus-client`, `prom/prometheus:v2.53.0`, `grafana/grafana:11.1.0`, `jaegertracing/all-in-one:1.58`

## Global Constraints

- Python 3.12, FastAPI ≥ 0.111.0, SQLAlchemy 2.0 async, `uv` for all package management
- mypy strict mode — add `# type: ignore[...]` where library stubs are missing, never suppress real errors
- ruff lint (E, F, I, UP) + ruff format, 88-char line limit — run before every commit
- No `Co-Authored-By: Claude` trailers in commits
- No `chore:` prefix on commit messages

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `src/prism/observability/__init__.py` | Create | Package marker |
| `src/prism/observability/metrics.py` | Create | All Prometheus metric objects |
| `src/prism/observability/tracing.py` | Create | OTel TracerProvider setup |
| `src/tests/unit/test_metrics.py` | Create | Unit tests for metrics registration + increment |
| `src/tests/unit/test_tracing.py` | Create | Smoke tests for setup_tracing() |
| `src/tests/integration/test_metrics_endpoint.py` | Create | Integration tests for /metrics + counter wiring |
| `pyproject.toml` | Modify | Add OTel + prometheus-client deps |
| `src/prism/config.py` | Modify | Add `otel_endpoint: str = ""` |
| `src/prism/main.py` | Modify | Mount /metrics, instrument with OTel |
| `src/prism/api/chat.py` | Modify | Record request/cache/cost/guardrail metrics |
| `src/prism/core/router.py` | Modify | Record circuit_breaker_open gauge |
| `docker-compose.yml` | Modify | Add prometheus, grafana, jaeger services |
| `deploy/prometheus/prometheus.yml` | Create | Prometheus scrape config |
| `deploy/grafana/provisioning/datasources/prometheus.yml` | Create | Grafana datasource |
| `deploy/grafana/provisioning/dashboards/dashboard.yml` | Create | Grafana dashboard provider |
| `deploy/grafana/provisioning/dashboards/prism.json` | Create | 6-panel Grafana dashboard |

---

## Task 1: Prometheus metrics module

**Files:**
- Create: `src/prism/observability/__init__.py`
- Create: `src/prism/observability/metrics.py`
- Modify: `pyproject.toml`
- Test: `src/tests/unit/test_metrics.py`

**Interfaces:**
- Produces: `request_counter`, `request_latency`, `cost_usd_total`, `cache_hits_total`, `cache_misses_total`, `guardrail_blocks_total`, `circuit_breaker_open` — imported by `chat.py` and `router.py` in later tasks

- [ ] **Step 1: Write the failing test**

```python
# src/tests/unit/test_metrics.py
from prometheus_client import REGISTRY


def test_all_metrics_registered() -> None:
    from prism.observability import metrics  # noqa: F401

    names = {m.name for m in REGISTRY.collect()}
    assert "prism_requests_total" in names
    assert "prism_request_latency_seconds" in names
    assert "prism_cost_usd_total" in names
    assert "prism_cache_hits_total" in names
    assert "prism_cache_misses_total" in names
    assert "prism_guardrail_blocks_total" in names
    assert "prism_circuit_breaker_open" in names


def test_request_counter_increments() -> None:
    from prism.observability.metrics import request_counter

    before = (
        REGISTRY.get_sample_value(
            "prism_requests_total",
            {"virtual_model": "fast", "provider_used": "ollama", "status_code": "200"},
        )
        or 0.0
    )
    request_counter.labels(
        virtual_model="fast", provider_used="ollama", status_code="200"
    ).inc()
    after = REGISTRY.get_sample_value(
        "prism_requests_total",
        {"virtual_model": "fast", "provider_used": "ollama", "status_code": "200"},
    )
    assert after == before + 1.0


def test_guardrail_blocks_counter_increments() -> None:
    from prism.observability.metrics import guardrail_blocks_total

    before = (
        REGISTRY.get_sample_value(
            "prism_guardrail_blocks_total", {"reason": "pii_detected"}
        )
        or 0.0
    )
    guardrail_blocks_total.labels(reason="pii_detected").inc()
    after = REGISTRY.get_sample_value(
        "prism_guardrail_blocks_total", {"reason": "pii_detected"}
    )
    assert after == before + 1.0


def test_circuit_breaker_gauge_sets() -> None:
    from prism.observability.metrics import circuit_breaker_open

    circuit_breaker_open.labels(provider="ollama").set(1.0)
    assert (
        REGISTRY.get_sample_value(
            "prism_circuit_breaker_open", {"provider": "ollama"}
        )
        == 1.0
    )
    circuit_breaker_open.labels(provider="ollama").set(0.0)
    assert (
        REGISTRY.get_sample_value(
            "prism_circuit_breaker_open", {"provider": "ollama"}
        )
        == 0.0
    )
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest src/tests/unit/test_metrics.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'prism.observability'`

- [ ] **Step 3: Install dependencies**

```bash
uv add "opentelemetry-sdk>=1.20.0" "opentelemetry-instrumentation-fastapi>=0.41b0" "opentelemetry-exporter-otlp-proto-http>=1.20.0" "prometheus-client>=0.19.0"
```

- [ ] **Step 4: Create the observability package**

`src/prism/observability/__init__.py` — empty file.

`src/prism/observability/metrics.py`:
```python
from prometheus_client import Counter, Gauge, Histogram

request_counter = Counter(
    "prism_requests_total",
    "Total chat completion requests",
    ["virtual_model", "provider_used", "status_code"],
)

request_latency = Histogram(
    "prism_request_latency_seconds",
    "Chat completion latency in seconds",
    ["virtual_model", "provider_used"],
    buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0],
)

cost_usd_total = Counter(
    "prism_cost_usd_total",
    "Total cost billed to providers in USD",
    ["virtual_model", "provider_used"],
)

cache_hits_total = Counter(
    "prism_cache_hits_total",
    "Exact cache hits",
    ["virtual_model"],
)

cache_misses_total = Counter(
    "prism_cache_misses_total",
    "Cache misses (request went to a live provider)",
    ["virtual_model"],
)

guardrail_blocks_total = Counter(
    "prism_guardrail_blocks_total",
    "Requests blocked by guardrail checks",
    ["reason"],
)

circuit_breaker_open = Gauge(
    "prism_circuit_breaker_open",
    "1 if the circuit breaker is open for this provider, 0 if closed",
    ["provider"],
)
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
uv run pytest src/tests/unit/test_metrics.py -v
```
Expected: 4 PASSED

- [ ] **Step 6: Commit**

```bash
uv run ruff check --fix src/prism/observability/ src/tests/unit/test_metrics.py
uv run ruff format src/prism/observability/ src/tests/unit/test_metrics.py
git add pyproject.toml uv.lock src/prism/observability/ src/tests/unit/test_metrics.py
git commit -m "add Prometheus custom metrics module"
```

---

## Task 2: OTel tracing + /metrics endpoint

**Files:**
- Create: `src/prism/observability/tracing.py`
- Create: `src/tests/unit/test_tracing.py`
- Modify: `src/prism/config.py` (add `otel_endpoint`)
- Modify: `src/prism/main.py` (setup tracing + mount /metrics)

**Interfaces:**
- Consumes: `setup_tracing(endpoint: str, service_name: str = "prism") -> None`
- Produces: OTel TracerProvider (global); `/metrics` ASGI endpoint on the FastAPI app

- [ ] **Step 1: Write the failing test**

```python
# src/tests/unit/test_tracing.py
from prism.observability.tracing import setup_tracing


def test_setup_tracing_noop_on_empty_endpoint() -> None:
    setup_tracing(endpoint="")


def test_setup_tracing_nonreachable_endpoint_does_not_raise() -> None:
    # OTel exporters don't open a connection at setup time — errors appear on flush
    setup_tracing(endpoint="http://localhost:9999", service_name="prism-test")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest src/tests/unit/test_tracing.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'prism.observability.tracing'`

- [ ] **Step 3: Create tracing.py**

```python
# src/prism/observability/tracing.py
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor


def setup_tracing(endpoint: str, service_name: str = "prism") -> None:
    if not endpoint:
        return
    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(endpoint=endpoint)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
```

- [ ] **Step 4: Add otel_endpoint to config.py**

In `src/prism/config.py`, add this line inside the `Settings` class body (after `admin_secret`):

```python
    otel_endpoint: str = ""
```

The full updated `Settings` class body (all fields):
```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "prism"
    postgres_password: str = "prism"
    postgres_db: str = "prism"
    redis_url: str = "redis://localhost:6379"
    log_level: str = "INFO"

    ollama_base_url: str = "http://localhost:11434"
    ollama_default_model: str = "llama3.2:3b"
    ollama_timeout_s: float = 60.0

    admin_secret: str = "change-me-in-production"
    otel_endpoint: str = ""

    @property
    def database_url(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def sqlalchemy_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )
```

- [ ] **Step 5: Update main.py**

```python
# src/prism/main.py
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor  # type: ignore[import-untyped]
from prometheus_client import make_asgi_app

from prism.api.admin import router as admin_router
from prism.api.chat import router as chat_router
from prism.api.health import router as health_router
from prism.config import settings
from prism.db.session import engine
from prism.observability.tracing import setup_tracing


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    setup_tracing(settings.otel_endpoint)
    yield
    await engine.dispose()


app = FastAPI(title="Prism LLM Gateway", version="0.4.0", lifespan=lifespan)

FastAPIInstrumentor.instrument_app(app)  # type: ignore[no-untyped-call]
app.mount("/metrics", make_asgi_app())  # type: ignore[arg-type]

app.include_router(health_router)
app.include_router(admin_router)
app.include_router(chat_router)
```

- [ ] **Step 6: Run unit tests**

```bash
uv run pytest src/tests/unit/ -v
```
Expected: all unit tests PASS (including the new tracing tests)

- [ ] **Step 7: Run mypy**

```bash
uv run mypy src/prism/
```
Expected: `Success: no issues found`

- [ ] **Step 8: Commit**

```bash
uv run ruff check --fix src/prism/observability/tracing.py src/prism/config.py src/prism/main.py src/tests/unit/test_tracing.py
uv run ruff format src/prism/observability/tracing.py src/prism/config.py src/prism/main.py src/tests/unit/test_tracing.py
git add src/prism/observability/tracing.py src/prism/config.py src/prism/main.py src/tests/unit/test_tracing.py uv.lock
git commit -m "add OpenTelemetry tracing and expose /metrics endpoint"
```

---

## Task 3: Instrument chat endpoint and router

Metrics are recorded at every decision point in `chat.py` (guardrail block, cache hit, live provider call) and the circuit-breaker gauge is updated in `router.py` each time `is_open()` is evaluated.

The guardrail `reason` string is normalized to a short label to keep Prometheus cardinality low: `"pii_detected"` for PII hits, `"prompt_injection"` for injection hits.

**Files:**
- Modify: `src/prism/api/chat.py`
- Modify: `src/prism/core/router.py`
- Test: `src/tests/integration/test_metrics_endpoint.py`

**Interfaces:**
- Consumes: all metric objects from `prism.observability.metrics`
- Consumes: `guardrail.reason: str | None` from `scan_prompt()`

- [ ] **Step 1: Write the failing integration tests**

```python
# src/tests/integration/test_metrics_endpoint.py
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from prism.main import app

ADMIN_HEADERS = {"Authorization": "Bearer change-me-in-production"}


@pytest.fixture
async def api_key(db: AsyncSession) -> str:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        team = await client.post(
            "/admin/teams",
            json={"name": "metrics-test"},
            headers=ADMIN_HEADERS,
        )
        key_resp = await client.post(
            "/admin/keys",
            json={"team_id": team.json()["id"]},
            headers=ADMIN_HEADERS,
        )
    return str(key_resp.json()["key"])


@pytest.mark.integration
async def test_metrics_endpoint_exposes_custom_metrics() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/metrics")
    assert resp.status_code == 200
    assert b"prism_requests_total" in resp.content
    assert b"prism_request_latency_seconds" in resp.content
    assert b"prism_guardrail_blocks_total" in resp.content


@pytest.mark.integration
async def test_guardrail_block_increments_counter(api_key: str) -> None:
    from prometheus_client import REGISTRY

    before = (
        REGISTRY.get_sample_value(
            "prism_guardrail_blocks_total", {"reason": "pii_detected"}
        )
        or 0.0
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/v1/chat/completions",
            json={
                "model": "fast",
                "messages": [
                    {
                        "role": "user",
                        "content": "My email is test@example.com, help me.",
                    }
                ],
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )
    assert resp.status_code == 400
    after = (
        REGISTRY.get_sample_value(
            "prism_guardrail_blocks_total", {"reason": "pii_detected"}
        )
        or 0.0
    )
    assert after > before


@pytest.mark.integration
async def test_cache_miss_then_hit_records_metrics(api_key: str) -> None:
    from prometheus_client import REGISTRY

    payload = {
        "model": "fast",
        "messages": [{"role": "user", "content": "What is 7 times 8?"}],
        "temperature": 0.0,
    }
    headers = {"Authorization": f"Bearer {api_key}"}

    hits_before = (
        REGISTRY.get_sample_value("prism_cache_hits_total", {"virtual_model": "fast"})
        or 0.0
    )
    misses_before = (
        REGISTRY.get_sample_value(
            "prism_cache_misses_total", {"virtual_model": "fast"}
        )
        or 0.0
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        first = await client.post(
            "/v1/chat/completions", json=payload, headers=headers
        )
        second = await client.post(
            "/v1/chat/completions", json=payload, headers=headers
        )

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["prism_metadata"]["cache_hit"] is True

    hits_after = (
        REGISTRY.get_sample_value("prism_cache_hits_total", {"virtual_model": "fast"})
        or 0.0
    )
    misses_after = (
        REGISTRY.get_sample_value(
            "prism_cache_misses_total", {"virtual_model": "fast"}
        )
        or 0.0
    )
    assert hits_after > hits_before
    assert misses_after > misses_before
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest src/tests/integration/test_metrics_endpoint.py -v -m integration
```
Expected: `test_metrics_endpoint_exposes_custom_metrics` PASS (endpoint already exists from Task 2). `test_guardrail_block_increments_counter` and `test_cache_miss_then_hit_records_metrics` FAIL — counters not yet wired.

- [ ] **Step 3: Update chat.py**

The key changes: normalize `guardrail.reason` into a short label; add metric recording at every branch exit.

```python
# src/prism/api/chat.py
import json
import time
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from prism.core.auth import validate_api_key
from prism.core.cache import exact_cache_key, get_exact, set_exact
from prism.core.cost import calculate_cost
from prism.core.guardrails import scan_prompt
from prism.core.router import PROVIDERS, route
from prism.db.models import ApiKey, ModelRoute, RequestLog
from prism.db.session import get_db
from prism.observability.metrics import (
    cache_hits_total,
    cache_misses_total,
    cost_usd_total,
    guardrail_blocks_total,
    request_counter,
    request_latency,
)

router = APIRouter(tags=["gateway"])


class Message(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    model: str
    messages: list[Message]
    temperature: float = 0.7
    stream: bool = False


def _guardrail_label(reason: str | None) -> str:
    if reason is None:
        return "unknown"
    if reason.startswith("PII"):
        return "pii_detected"
    if "injection" in reason.lower():
        return "prompt_injection"
    return "unknown"


@router.post("/v1/chat/completions")
async def chat_completions(
    body: ChatRequest,
    api_key: ApiKey = Depends(validate_api_key),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    if body.stream:
        raise HTTPException(status_code=400, detail="Streaming not supported yet")

    messages = [m.model_dump() for m in body.messages]
    full_text = " ".join(m.get("content", "") for m in messages)

    guardrail = scan_prompt(full_text)
    if guardrail.flagged:
        guardrail_blocks_total.labels(reason=_guardrail_label(guardrail.reason)).inc()
        request_counter.labels(
            virtual_model=body.model, provider_used="blocked", status_code="400"
        ).inc()
        log = RequestLog(
            api_key_id=api_key.id,
            virtual_model=body.model,
            provider_used="blocked",
            status_code=400,
            guardrail_flag=guardrail.reason,
        )
        db.add(log)
        await db.commit()
        raise HTTPException(
            status_code=400,
            detail=f"Request blocked by guardrail: {guardrail.reason}",
        )

    start = time.perf_counter()
    cache_key = exact_cache_key(body.model, messages, body.temperature)
    cached = await get_exact(cache_key)

    if cached is not None:
        latency_ms = int((time.perf_counter() - start) * 1000)
        cached_data: dict[str, object] = json.loads(cached)
        cache_hits_total.labels(virtual_model=body.model).inc()
        request_counter.labels(
            virtual_model=body.model, provider_used="cache", status_code="200"
        ).inc()
        request_latency.labels(virtual_model=body.model, provider_used="cache").observe(
            latency_ms / 1000
        )
        log = RequestLog(
            api_key_id=api_key.id,
            virtual_model=body.model,
            provider_used="cache",
            cache_hit=True,
            cost_usd=Decimal("0"),
            latency_ms=latency_ms,
            status_code=200,
        )
        db.add(log)
        await db.commit()
        return {
            **cached_data,
            "prism_metadata": {
                "provider_used": "cache",
                "cache_hit": True,
                "fallback_triggered": False,
                "cost_usd": 0.0,
                "latency_ms": latency_ms,
            },
        }

    rows = await db.execute(
        select(ModelRoute)
        .where(ModelRoute.virtual_model == body.model)
        .order_by(ModelRoute.priority)
    )
    routes = [
        (r.provider, r.real_model, r.priority) for r in rows.scalars().all()
    ]

    if not routes:
        raise HTTPException(
            status_code=404,
            detail=f"No routes configured for model '{body.model}'",
        )

    chat_result, provider_name, real_model, fallback_triggered = await route(
        routes=routes,
        providers=PROVIDERS,
        messages=messages,
        temperature=body.temperature,
    )

    latency_ms = int((time.perf_counter() - start) * 1000)
    cost: Decimal = calculate_cost(
        provider_name,
        real_model,
        chat_result.prompt_tokens,
        chat_result.completion_tokens,
    )

    cache_misses_total.labels(virtual_model=body.model).inc()
    request_counter.labels(
        virtual_model=body.model, provider_used=provider_name, status_code="200"
    ).inc()
    request_latency.labels(
        virtual_model=body.model, provider_used=provider_name
    ).observe(latency_ms / 1000)
    cost_usd_total.labels(
        virtual_model=body.model, provider_used=provider_name
    ).inc(float(cost))

    await set_exact(cache_key, json.dumps(chat_result.raw))

    log = RequestLog(
        api_key_id=api_key.id,
        virtual_model=body.model,
        provider_used=provider_name,
        fallback_triggered=fallback_triggered,
        cache_hit=False,
        prompt_tokens=chat_result.prompt_tokens,
        completion_tokens=chat_result.completion_tokens,
        cost_usd=cost,
        latency_ms=latency_ms,
        status_code=200,
    )
    db.add(log)
    await db.commit()

    return {
        **chat_result.raw,
        "prism_metadata": {
            "provider_used": provider_name,
            "cache_hit": False,
            "fallback_triggered": fallback_triggered,
            "cost_usd": float(cost),
            "latency_ms": latency_ms,
        },
    }
```

- [ ] **Step 4: Update router.py**

Add `circuit_breaker_open` gauge updates at `is_open()` check and after `record_failure()` / `record_success()`:

```python
# src/prism/core/router.py
from fastapi import HTTPException

from prism.core.circuit_breaker import CircuitBreaker, circuit_breaker
from prism.observability.metrics import circuit_breaker_open
from prism.providers.anthropic_provider import AnthropicProvider
from prism.providers.base import BaseProvider, ChatResult
from prism.providers.ollama_provider import OllamaProvider
from prism.providers.openai_provider import OpenAIProvider

PROVIDERS: dict[str, BaseProvider] = {
    "ollama": OllamaProvider(),
    "openai": OpenAIProvider(),
    "anthropic": AnthropicProvider(),
}


async def route(
    routes: list[tuple[str, str, int]],
    providers: dict[str, BaseProvider],
    messages: list[dict[str, str]],
    temperature: float,
    cb: CircuitBreaker = circuit_breaker,
) -> tuple[ChatResult, str, str, bool]:
    """Try each (provider, model) in priority order, return first success.

    routes: list of (provider_name, real_model, priority) sorted by priority
    Returns: (result, provider_name, real_model, fallback_triggered)
    Raises HTTPException(503) if all providers fail or are circuit-broken.
    """
    fallback_triggered = False
    last_error: Exception | None = None

    for provider_name, real_model, _ in routes:
        is_open = cb.is_open(provider_name)
        circuit_breaker_open.labels(provider=provider_name).set(
            1.0 if is_open else 0.0
        )
        if is_open:
            fallback_triggered = True
            continue

        provider = providers.get(provider_name)
        if provider is None:
            fallback_triggered = True
            continue

        try:
            result = await provider.chat(
                messages=messages,
                model=real_model,
                temperature=temperature,
            )
            cb.record_success(provider_name)
            circuit_breaker_open.labels(provider=provider_name).set(0.0)
            return result, provider_name, real_model, fallback_triggered
        except Exception as exc:
            cb.record_failure(provider_name)
            circuit_breaker_open.labels(provider=provider_name).set(
                1.0 if cb.is_open(provider_name) else 0.0
            )
            last_error = exc
            fallback_triggered = True

    raise HTTPException(
        status_code=503,
        detail=f"All providers failed. Last error: {last_error}",
    )
```

- [ ] **Step 5: Run all tests**

```bash
uv run pytest src/tests/ -v -m integration
```
Expected: all 3 new integration tests PASS; existing 51 tests still PASS

- [ ] **Step 6: Run mypy**

```bash
uv run mypy src/prism/
```
Expected: `Success: no issues found`

- [ ] **Step 7: Commit**

```bash
uv run ruff check --fix src/prism/api/chat.py src/prism/core/router.py src/tests/integration/test_metrics_endpoint.py
uv run ruff format src/prism/api/chat.py src/prism/core/router.py src/tests/integration/test_metrics_endpoint.py
git add src/prism/api/chat.py src/prism/core/router.py src/tests/integration/test_metrics_endpoint.py
git commit -m "instrument chat endpoint and router with Prometheus metrics"
```

---

## Task 4: Infrastructure — Prometheus, Grafana, Jaeger

**Files:**
- Modify: `docker-compose.yml`
- Create: `deploy/prometheus/prometheus.yml`
- Create: `deploy/grafana/provisioning/datasources/prometheus.yml`
- Create: `deploy/grafana/provisioning/dashboards/dashboard.yml`
- Create: `deploy/grafana/provisioning/dashboards/prism.json`

**Interfaces:**
- Consumes: `/metrics` endpoint on `app:8000` (from Task 2)
- Produces: Grafana at `localhost:3000`, Jaeger UI at `localhost:16686`, Prometheus at `localhost:9090`

- [ ] **Step 1: Update docker-compose.yml**

```yaml
services:
  postgres:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_USER: prism
      POSTGRES_PASSWORD: prism
      POSTGRES_DB: prism
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U prism"]
      interval: 5s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 5s
      retries: 5

  jaeger:
    image: jaegertracing/all-in-one:1.58
    environment:
      - COLLECTOR_OTLP_ENABLED=true
    ports:
      - "16686:16686"
      - "4318:4318"

  app:
    build:
      context: .
      dockerfile: deploy/docker/Dockerfile
    ports:
      - "8000:8000"
    env_file:
      - .env
    environment:
      POSTGRES_HOST: postgres
      REDIS_URL: redis://redis:6379
      OTEL_ENDPOINT: http://jaeger:4318/v1/traces
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy

  prometheus:
    image: prom/prometheus:v2.53.0
    volumes:
      - ./deploy/prometheus/prometheus.yml:/etc/prometheus/prometheus.yml:ro
    ports:
      - "9090:9090"
    depends_on:
      - app

  grafana:
    image: grafana/grafana:11.1.0
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=admin
      - GF_USERS_ALLOW_SIGN_UP=false
    volumes:
      - ./deploy/grafana/provisioning:/etc/grafana/provisioning:ro
      - grafana_data:/var/lib/grafana
    ports:
      - "3000:3000"
    depends_on:
      - prometheus

volumes:
  postgres_data:
  grafana_data:
```

- [ ] **Step 2: Create deploy/prometheus/prometheus.yml**

```yaml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:
  - job_name: prism
    static_configs:
      - targets: ['app:8000']
    metrics_path: /metrics
```

- [ ] **Step 3: Create Grafana datasource provisioning**

```yaml
# deploy/grafana/provisioning/datasources/prometheus.yml
apiVersion: 1

datasources:
  - name: Prometheus
    type: prometheus
    access: proxy
    url: http://prometheus:9090
    isDefault: true
    editable: false
```

- [ ] **Step 4: Create Grafana dashboard provider**

```yaml
# deploy/grafana/provisioning/dashboards/dashboard.yml
apiVersion: 1

providers:
  - name: prism
    folder: Prism
    type: file
    options:
      path: /etc/grafana/provisioning/dashboards
```

- [ ] **Step 5: Create the Grafana dashboard JSON**

Save this as `deploy/grafana/provisioning/dashboards/prism.json`:

```json
{
  "uid": "prism-gateway",
  "title": "Prism LLM Gateway",
  "tags": ["prism"],
  "timezone": "browser",
  "schemaVersion": 38,
  "version": 1,
  "refresh": "10s",
  "time": { "from": "now-30m", "to": "now" },
  "templating": {
    "list": [
      {
        "name": "datasource",
        "type": "datasource",
        "pluginId": "prometheus",
        "hide": 2,
        "query": "prometheus"
      }
    ]
  },
  "panels": [
    {
      "id": 1,
      "title": "Request Rate (req/s)",
      "type": "timeseries",
      "gridPos": { "h": 8, "w": 12, "x": 0, "y": 0 },
      "datasource": { "type": "prometheus", "uid": "${datasource}" },
      "targets": [
        {
          "expr": "sum(rate(prism_requests_total[1m])) by (provider_used)",
          "legendFormat": "{{provider_used}}"
        }
      ],
      "fieldConfig": { "defaults": { "unit": "reqps" } }
    },
    {
      "id": 2,
      "title": "P50 / P95 Latency",
      "type": "timeseries",
      "gridPos": { "h": 8, "w": 12, "x": 12, "y": 0 },
      "datasource": { "type": "prometheus", "uid": "${datasource}" },
      "targets": [
        {
          "expr": "histogram_quantile(0.95, sum(rate(prism_request_latency_seconds_bucket[5m])) by (le, virtual_model))",
          "legendFormat": "p95 {{virtual_model}}"
        },
        {
          "expr": "histogram_quantile(0.50, sum(rate(prism_request_latency_seconds_bucket[5m])) by (le, virtual_model))",
          "legendFormat": "p50 {{virtual_model}}"
        }
      ],
      "fieldConfig": { "defaults": { "unit": "s" } }
    },
    {
      "id": 3,
      "title": "Cache Hit Rate",
      "type": "stat",
      "gridPos": { "h": 8, "w": 6, "x": 0, "y": 8 },
      "datasource": { "type": "prometheus", "uid": "${datasource}" },
      "targets": [
        {
          "expr": "100 * sum(rate(prism_cache_hits_total[5m])) / (sum(rate(prism_cache_hits_total[5m])) + sum(rate(prism_cache_misses_total[5m])))",
          "legendFormat": ""
        }
      ],
      "fieldConfig": {
        "defaults": {
          "unit": "percent",
          "min": 0,
          "max": 100,
          "thresholds": {
            "mode": "absolute",
            "steps": [
              { "color": "red", "value": null },
              { "color": "yellow", "value": 50 },
              { "color": "green", "value": 80 }
            ]
          }
        }
      },
      "options": { "colorMode": "background", "graphMode": "none" }
    },
    {
      "id": 4,
      "title": "Cost / min (USD)",
      "type": "timeseries",
      "gridPos": { "h": 8, "w": 18, "x": 6, "y": 8 },
      "datasource": { "type": "prometheus", "uid": "${datasource}" },
      "targets": [
        {
          "expr": "sum(rate(prism_cost_usd_total[1m])) by (provider_used) * 60",
          "legendFormat": "{{provider_used}}"
        }
      ],
      "fieldConfig": { "defaults": { "unit": "currencyUSD" } }
    },
    {
      "id": 5,
      "title": "Guardrail Blocks (req/s)",
      "type": "timeseries",
      "gridPos": { "h": 8, "w": 12, "x": 0, "y": 16 },
      "datasource": { "type": "prometheus", "uid": "${datasource}" },
      "targets": [
        {
          "expr": "sum(rate(prism_guardrail_blocks_total[1m])) by (reason)",
          "legendFormat": "{{reason}}"
        }
      ],
      "fieldConfig": { "defaults": { "unit": "reqps" } }
    },
    {
      "id": 6,
      "title": "Circuit Breaker State",
      "type": "stat",
      "gridPos": { "h": 8, "w": 12, "x": 12, "y": 16 },
      "datasource": { "type": "prometheus", "uid": "${datasource}" },
      "targets": [
        {
          "expr": "prism_circuit_breaker_open",
          "legendFormat": "{{provider}}"
        }
      ],
      "fieldConfig": {
        "defaults": {
          "mappings": [
            {
              "type": "value",
              "options": {
                "0": { "text": "CLOSED", "color": "green", "index": 0 },
                "1": { "text": "OPEN", "color": "red", "index": 1 }
              }
            }
          ],
          "thresholds": {
            "mode": "absolute",
            "steps": [
              { "color": "green", "value": null },
              { "color": "red", "value": 1 }
            ]
          }
        }
      },
      "options": { "colorMode": "background", "graphMode": "none" }
    }
  ]
}
```

- [ ] **Step 6: Smoke test**

```bash
docker-compose up --build -d
```

Wait 20 seconds for all services to start, then verify:

```bash
# Prometheus scraping the app
curl -s http://localhost:9090/api/v1/targets | python3 -c "import sys,json; targets=json.load(sys.stdin)['data']['activeTargets']; print([t['health'] for t in targets if t['labels']['job']=='prism'])"
# Expected: ['up']

# Metrics endpoint
curl -s http://localhost:8000/metrics | grep prism_requests_total
# Expected: # HELP prism_requests_total ...

# Grafana (login admin/admin, Dashboards → Prism → Prism LLM Gateway)
open http://localhost:3000

# Jaeger UI
open http://localhost:16686
```

Generate live traffic:
```bash
# First get an API key from your running app, then:
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer <your-key>" \
  -H "Content-Type: application/json" \
  -d '{"model": "fast", "messages": [{"role": "user", "content": "Hello, world!"}]}'
```

Watch Grafana: Request Rate and P95 Latency panels should update within 15 seconds.

- [ ] **Step 7: Commit milestone**

```bash
git add docker-compose.yml deploy/prometheus/ deploy/grafana/
git commit -m "add Prometheus, Grafana, and Jaeger with provisioned dashboard"
git add -A
git commit -m "Phase 4 complete — OpenTelemetry tracing, Prometheus metrics, Grafana dashboards"
```
