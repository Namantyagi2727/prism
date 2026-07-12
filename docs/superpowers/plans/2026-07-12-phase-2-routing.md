# Phase 2 — Multi-Provider Routing, Fallback Chain, Circuit Breaker

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add mock OpenAI and Anthropic providers, a fallback chain that tries providers in priority order, and a hand-rolled circuit breaker that opens after repeated failures — so killing Ollama causes automatic failover to a mock, logged with `fallback_triggered=true`.

**Architecture:** Three layers added on top of Phase 1: (1) mock OpenAI and Anthropic providers that return deterministic responses without real API keys; (2) a router that loads all `model_routes` rows for a virtual model, tries them in priority order, and falls back on `httpx.HTTPError` or timeout; (3) a per-provider circuit breaker using a shared in-process state dict — closed → open (after 3 failures in 60 s) → half-open (after 30 s cooldown) → closed. The `chat.py` endpoint is refactored to delegate to the router instead of calling Ollama directly.

**Tech Stack:** Python 3.12, FastAPI, httpx, SQLAlchemy 2.0 async, pytest-asyncio, existing models + providers

## Global Constraints

- Python >= 3.12 strictly; `src` layout; `uv` for packages
- All source files pass `mypy --strict` with `sqlalchemy.ext.mypy.plugin`
- TDD: write failing test → implement → verify pass → commit
- Never store raw API keys; admin endpoints protected by `ADMIN_SECRET`
- Line length <= 88 chars (ruff enforced); imports sorted isort-style
- User pushes to GitHub — plan provides only `git add` / `git commit` commands

---

## File Map

| File | Action | Purpose |
|---|---|---|
| `src/prism/providers/openai_provider.py` | Create | Mock OpenAI — returns fixed response, no real key needed |
| `src/prism/providers/anthropic_provider.py` | Create | Mock Anthropic — same pattern |
| `src/prism/core/circuit_breaker.py` | Create | Per-provider state machine: closed / open / half-open |
| `src/prism/core/router.py` | Create | Loads fallback chain from DB, tries each provider, respects circuit breaker |
| `src/prism/api/chat.py` | Modify | Replace direct Ollama call with `router.route()` |
| `alembic/versions/` | Create | Migration seeding two more model_routes rows (openai + anthropic fallbacks) |
| `src/tests/unit/test_circuit_breaker.py` | Create | Unit tests for state machine transitions |
| `src/tests/unit/test_router.py` | Create | Unit tests for fallback ordering and circuit breaker integration |
| `src/tests/integration/test_fallback.py` | Create | Integration test: mock Ollama failure → fallback logged |

---

## Task 1: Mock providers (OpenAI + Anthropic)

**Files:**
- Create: `src/prism/providers/openai_provider.py`
- Create: `src/prism/providers/anthropic_provider.py`
- Test: `src/tests/unit/test_mock_providers.py`

**Interfaces:**
- Consumes: `BaseProvider`, `ChatResult` from `prism.providers.base`
- Produces:
  - `OpenAIProvider().chat(messages, model, **kwargs) -> ChatResult`
  - `AnthropicProvider().chat(messages, model, **kwargs) -> ChatResult`
  - Both return a `ChatResult` with `content="[mock openai response]"` / `"[mock anthropic response]"`, `prompt_tokens=10`, `completion_tokens=5`, and a plausible `raw` dict shaped like each provider's real response.

---

- [ ] **Step 1: Write the failing unit tests**

Create `src/tests/unit/test_mock_providers.py`:

```python
import pytest

from prism.providers.anthropic_provider import AnthropicProvider
from prism.providers.openai_provider import OpenAIProvider


@pytest.mark.asyncio
async def test_openai_provider_returns_chat_result() -> None:
    provider = OpenAIProvider()
    result = await provider.chat(
        messages=[{"role": "user", "content": "hi"}],
        model="gpt-4o-mini",
    )
    assert result.content == "[mock openai response]"
    assert result.prompt_tokens == 10
    assert result.completion_tokens == 5
    assert "choices" in result.raw


@pytest.mark.asyncio
async def test_anthropic_provider_returns_chat_result() -> None:
    provider = AnthropicProvider()
    result = await provider.chat(
        messages=[{"role": "user", "content": "hi"}],
        model="claude-haiku-4-5-20251001",
    )
    assert result.content == "[mock anthropic response]"
    assert result.prompt_tokens == 10
    assert result.completion_tokens == 5
    assert "choices" in result.raw
```

- [ ] **Step 2: Run to verify they fail**

```bash
pytest src/tests/unit/test_mock_providers.py -v
```

Expected: `ImportError` — modules don't exist yet.

- [ ] **Step 3: Write `src/prism/providers/openai_provider.py`**

```python
from prism.providers.base import BaseProvider, ChatResult


class OpenAIProvider(BaseProvider):
    async def chat(
        self,
        messages: list[dict[str, str]],
        model: str,
        **kwargs: object,
    ) -> ChatResult:
        return ChatResult(
            content="[mock openai response]",
            prompt_tokens=10,
            completion_tokens=5,
            raw={
                "id": "chatcmpl-mock",
                "object": "chat.completion",
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": "[mock openai response]",
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "total_tokens": 15,
                },
            },
        )
```

- [ ] **Step 4: Write `src/prism/providers/anthropic_provider.py`**

```python
from prism.providers.base import BaseProvider, ChatResult


class AnthropicProvider(BaseProvider):
    async def chat(
        self,
        messages: list[dict[str, str]],
        model: str,
        **kwargs: object,
    ) -> ChatResult:
        return ChatResult(
            content="[mock anthropic response]",
            prompt_tokens=10,
            completion_tokens=5,
            raw={
                "id": "chatcmpl-mock-anthropic",
                "object": "chat.completion",
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": "[mock anthropic response]",
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "total_tokens": 15,
                },
            },
        )
```

- [ ] **Step 5: Run unit tests to verify they pass**

```bash
pytest src/tests/unit/test_mock_providers.py -v
```

Expected: 2 tests PASSED.

- [ ] **Step 6: Type-check**

```bash
mypy src/prism/providers/openai_provider.py src/prism/providers/anthropic_provider.py
```

Expected: `Success: no issues found in 2 source files`

- [ ] **Step 7: Commit**

```bash
git add src/prism/providers/openai_provider.py src/prism/providers/anthropic_provider.py src/tests/unit/test_mock_providers.py
git commit -m "add mock OpenAI and Anthropic providers"
```

---

## Task 2: Circuit breaker

**Files:**
- Create: `src/prism/core/circuit_breaker.py`
- Create: `src/tests/unit/test_circuit_breaker.py`

**Interfaces:**
- Produces:
  - `CircuitBreaker` class with:
    - `is_open(provider: str) -> bool` — returns `True` when the breaker is open (calls should be skipped)
    - `record_failure(provider: str) -> None` — increments failure count; opens breaker after 3 failures within 60 s
    - `record_success(provider: str) -> None` — resets failure count, closes breaker
  - Module-level singleton: `circuit_breaker = CircuitBreaker()`
  - Constants: `FAILURE_THRESHOLD = 3`, `OPEN_DURATION_S = 30`

---

- [ ] **Step 1: Write the failing unit tests**

Create `src/tests/unit/test_circuit_breaker.py`:

```python
import time

from prism.core.circuit_breaker import CircuitBreaker


def test_initially_closed() -> None:
    cb = CircuitBreaker()
    assert cb.is_open("ollama") is False


def test_opens_after_threshold_failures() -> None:
    cb = CircuitBreaker()
    cb.record_failure("ollama")
    cb.record_failure("ollama")
    assert cb.is_open("ollama") is False  # not yet
    cb.record_failure("ollama")
    assert cb.is_open("ollama") is True   # 3rd failure opens it


def test_success_resets_failures() -> None:
    cb = CircuitBreaker()
    cb.record_failure("ollama")
    cb.record_failure("ollama")
    cb.record_success("ollama")
    cb.record_failure("ollama")
    cb.record_failure("ollama")
    assert cb.is_open("ollama") is False  # reset means we need 3 fresh failures


def test_half_open_after_cooldown() -> None:
    cb = CircuitBreaker(open_duration_s=0)  # 0-second cooldown for test
    cb.record_failure("ollama")
    cb.record_failure("ollama")
    cb.record_failure("ollama")
    assert cb.is_open("ollama") is True
    # With 0-second cooldown the breaker is immediately half-open → treated as closed
    time.sleep(0.01)
    assert cb.is_open("ollama") is False


def test_independent_providers() -> None:
    cb = CircuitBreaker()
    cb.record_failure("ollama")
    cb.record_failure("ollama")
    cb.record_failure("ollama")
    assert cb.is_open("ollama") is True
    assert cb.is_open("openai") is False
```

- [ ] **Step 2: Run to verify they fail**

```bash
pytest src/tests/unit/test_circuit_breaker.py -v
```

Expected: `ImportError`.

- [ ] **Step 3: Write `src/prism/core/circuit_breaker.py`**

```python
import time
from dataclasses import dataclass, field

FAILURE_THRESHOLD = 3
OPEN_DURATION_S = 30


@dataclass
class _State:
    failures: int = 0
    opened_at: float | None = None


class CircuitBreaker:
    def __init__(
        self,
        failure_threshold: int = FAILURE_THRESHOLD,
        open_duration_s: float = OPEN_DURATION_S,
    ) -> None:
        self._threshold = failure_threshold
        self._duration = open_duration_s
        self._states: dict[str, _State] = {}

    def _state(self, provider: str) -> _State:
        if provider not in self._states:
            self._states[provider] = _State()
        return self._states[provider]

    def is_open(self, provider: str) -> bool:
        s = self._state(provider)
        if s.opened_at is None:
            return False
        if time.time() - s.opened_at >= self._duration:
            # half-open: allow one probe through
            s.opened_at = None
            return False
        return True

    def record_failure(self, provider: str) -> None:
        s = self._state(provider)
        s.failures += 1
        if s.failures >= self._threshold:
            s.opened_at = time.time()

    def record_success(self, provider: str) -> None:
        self._states[provider] = _State()


circuit_breaker = CircuitBreaker()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest src/tests/unit/test_circuit_breaker.py -v
```

Expected: 5 tests PASSED.

- [ ] **Step 5: Type-check**

```bash
mypy src/prism/core/circuit_breaker.py
```

Expected: `Success: no issues found in 1 source file`

- [ ] **Step 6: Commit**

```bash
git add src/prism/core/circuit_breaker.py src/tests/unit/test_circuit_breaker.py
git commit -m "add circuit breaker with closed/open/half-open state machine"
```

---

## Task 3: Provider router + fallback chain

**Files:**
- Create: `src/prism/core/router.py`
- Create: `src/tests/unit/test_router.py`

**Interfaces:**
- Consumes:
  - `ModelRoute` ORM model from `prism.db.models`
  - `BaseProvider`, `ChatResult` from `prism.providers.base`
  - `OllamaProvider` from `prism.providers.ollama_provider`
  - `OpenAIProvider` from `prism.providers.openai_provider`
  - `AnthropicProvider` from `prism.providers.anthropic_provider`
  - `circuit_breaker` singleton from `prism.core.circuit_breaker`
- Produces:
  - `route(routes, messages, temperature) -> tuple[ChatResult, str, str, bool]`
    - Returns `(result, provider_name, real_model, fallback_triggered)`
    - Raises `HTTPException(503)` if all providers fail or are open

---

- [ ] **Step 1: Write the failing unit tests**

Create `src/tests/unit/test_router.py`:

```python
import pytest

from prism.core.circuit_breaker import CircuitBreaker
from prism.core.router import route
from prism.providers.base import ChatResult


class _AlwaysFailProvider:
    async def chat(
        self, messages: list[dict[str, str]], model: str, **kwargs: object
    ) -> ChatResult:
        raise RuntimeError("provider down")


class _SucceedProvider:
    async def chat(
        self, messages: list[dict[str, str]], model: str, **kwargs: object
    ) -> ChatResult:
        return ChatResult(
            content="ok",
            prompt_tokens=5,
            completion_tokens=3,
            raw={"choices": [{"message": {"content": "ok"}}]},
        )


@pytest.mark.asyncio
async def test_uses_first_provider_when_healthy() -> None:
    providers = {"succeed": _SucceedProvider()}
    routes = [("succeed", "model-a", 1)]
    result, provider, model, fallback = await route(
        routes, providers, [{"role": "user", "content": "hi"}], 0.7,
        cb=CircuitBreaker(),
    )
    assert provider == "succeed"
    assert fallback is False


@pytest.mark.asyncio
async def test_falls_back_on_failure() -> None:
    providers = {
        "fail": _AlwaysFailProvider(),
        "succeed": _SucceedProvider(),
    }
    routes = [("fail", "model-a", 1), ("succeed", "model-b", 2)]
    result, provider, model, fallback = await route(
        routes, providers, [{"role": "user", "content": "hi"}], 0.7,
        cb=CircuitBreaker(),
    )
    assert provider == "succeed"
    assert fallback is True


@pytest.mark.asyncio
async def test_raises_503_when_all_fail() -> None:
    from fastapi import HTTPException

    providers = {"fail": _AlwaysFailProvider()}
    routes = [("fail", "model-a", 1)]
    with pytest.raises(HTTPException) as exc_info:
        await route(
            routes, providers, [{"role": "user", "content": "hi"}], 0.7,
            cb=CircuitBreaker(),
        )
    assert exc_info.value.status_code == 503


@pytest.mark.asyncio
async def test_skips_open_circuit() -> None:
    cb = CircuitBreaker()
    # Open the circuit for "fail"
    for _ in range(3):
        cb.record_failure("fail")

    providers = {
        "fail": _AlwaysFailProvider(),
        "succeed": _SucceedProvider(),
    }
    routes = [("fail", "model-a", 1), ("succeed", "model-b", 2)]
    result, provider, model, fallback = await route(
        routes, providers, [{"role": "user", "content": "hi"}], 0.7,
        cb=cb,
    )
    assert provider == "succeed"
    assert fallback is True
```

- [ ] **Step 2: Run to verify they fail**

```bash
pytest src/tests/unit/test_router.py -v
```

Expected: `ImportError`.

- [ ] **Step 3: Write `src/prism/core/router.py`**

```python
from fastapi import HTTPException

from prism.core.circuit_breaker import CircuitBreaker, circuit_breaker
from prism.providers.anthropic_provider import AnthropicProvider
from prism.providers.base import BaseProvider, ChatResult
from prism.providers.ollama_provider import OllamaProvider
from prism.providers.openai_provider import OpenAIProvider

# Module-level provider registry — one instance per provider type
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
        if cb.is_open(provider_name):
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
            return result, provider_name, real_model, fallback_triggered
        except Exception as exc:
            cb.record_failure(provider_name)
            last_error = exc
            fallback_triggered = True

    raise HTTPException(
        status_code=503,
        detail=f"All providers failed. Last error: {last_error}",
    )
```

- [ ] **Step 4: Run unit tests to verify they pass**

```bash
pytest src/tests/unit/test_router.py -v
```

Expected: 4 tests PASSED.

- [ ] **Step 5: Type-check**

```bash
mypy src/prism/core/router.py
```

Expected: `Success: no issues found in 1 source file`

- [ ] **Step 6: Commit**

```bash
git add src/prism/core/router.py src/tests/unit/test_router.py
git commit -m "add provider router with fallback chain and circuit breaker integration"
```

---

## Task 4: Seed fallback routes + wire router into chat endpoint

**Files:**
- Create: `alembic/versions/<hash>_seed_fallback_routes.py`
- Modify: `src/prism/api/chat.py`
- Create: `src/tests/integration/test_fallback.py`

**Interfaces:**
- Consumes:
  - `route()` from `prism.core.router`
  - `PROVIDERS` dict from `prism.core.router`
  - `ModelRoute` rows now include openai (priority 2) and anthropic (priority 3) for virtual model `"fast"`
- Produces:
  - `chat.py` delegates provider selection to `route()` instead of calling Ollama directly
  - `fallback_triggered=True` in `prism_metadata` and `request_log` when fallback occurs

---

- [ ] **Step 1: Create the Alembic migration to seed fallback routes**

```bash
alembic revision -m "seed fallback routes"
```

Open the generated file in `alembic/versions/` and replace its `upgrade()` and `downgrade()` with:

```python
import uuid

from alembic import op


def upgrade() -> None:
    op.execute(
        "INSERT INTO model_routes "
        "(id, virtual_model, priority, provider, real_model, timeout_ms) VALUES "
        f"('{uuid.uuid4()}', 'fast', 2, 'openai', 'gpt-4o-mini', 10000), "
        f"('{uuid.uuid4()}', 'fast', 3, 'anthropic', "
        f"'claude-haiku-4-5-20251001', 10000)"
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM model_routes "
        "WHERE virtual_model = 'fast' AND provider IN ('openai', 'anthropic')"
    )
```

- [ ] **Step 2: Run the migration**

```bash
alembic upgrade head
```

Expected: runs cleanly. Verify:

```bash
docker-compose exec postgres psql -U prism -d prism \
  -c "SELECT virtual_model, priority, provider, real_model FROM model_routes ORDER BY priority;"
```

Expected: 3 rows — ollama (1), openai (2), anthropic (3).

- [ ] **Step 3: Write the failing integration tests**

Create `src/tests/integration/test_fallback.py`:

```python
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from prism.db.models import RequestLog
from prism.main import app

ADMIN_HEADERS = {"Authorization": "Bearer change-me-in-production"}


@pytest.fixture
async def api_key(db: AsyncSession) -> str:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        team = await client.post(
            "/admin/teams",
            json={"name": "fallback-test"},
            headers=ADMIN_HEADERS,
        )
        key_resp = await client.post(
            "/admin/keys",
            json={"team_id": team.json()["id"]},
            headers=ADMIN_HEADERS,
        )
    return str(key_resp.json()["key"])


@pytest.mark.integration
async def test_fallback_when_ollama_fails(
    api_key: str, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Force Ollama to fail; expect fallback to openai mock."""
    from prism.providers.ollama_provider import OllamaProvider

    async def _fail(
        self: OllamaProvider,
        messages: list[dict[str, str]],
        model: str,
        **kwargs: object,
    ) -> None:
        raise RuntimeError("simulated Ollama failure")

    monkeypatch.setattr(OllamaProvider, "chat", _fail)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/v1/chat/completions",
            json={
                "model": "fast",
                "messages": [{"role": "user", "content": "hi"}],
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["prism_metadata"]["provider_used"] == "openai"
    assert data["prism_metadata"]["fallback_triggered"] is True

    result = await db.execute(
        select(RequestLog).order_by(RequestLog.created_at.desc()).limit(1)
    )
    log = result.scalar_one()
    assert log.provider_used == "openai"
    assert log.fallback_triggered is True


@pytest.mark.integration
async def test_normal_request_not_flagged_as_fallback(
    api_key: str, db: AsyncSession
) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/v1/chat/completions",
            json={
                "model": "fast",
                "messages": [{"role": "user", "content": "Say hi"}],
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )

    assert response.status_code == 200
    assert response.json()["prism_metadata"]["fallback_triggered"] is False
```

- [ ] **Step 4: Run to verify they fail**

```bash
pytest src/tests/integration/test_fallback.py -v -m integration
```

Expected: tests fail — `chat.py` still calls Ollama directly.

- [ ] **Step 5: Rewrite `src/prism/api/chat.py` to use the router**

```python
import time
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from prism.core.auth import validate_api_key
from prism.core.cost import calculate_cost
from prism.core.router import PROVIDERS, route
from prism.db.models import ApiKey, ModelRoute, RequestLog
from prism.db.session import get_db

router = APIRouter(tags=["gateway"])


class Message(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    model: str
    messages: list[Message]
    temperature: float = 0.7
    stream: bool = False


@router.post("/v1/chat/completions")
async def chat_completions(
    body: ChatRequest,
    api_key: ApiKey = Depends(validate_api_key),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    if body.stream:
        raise HTTPException(
            status_code=400, detail="Streaming not supported yet"
        )

    start = time.perf_counter()

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
        messages=[m.model_dump() for m in body.messages],
        temperature=body.temperature,
    )

    latency_ms = int((time.perf_counter() - start) * 1000)
    cost: Decimal = calculate_cost(
        provider_name,
        real_model,
        chat_result.prompt_tokens,
        chat_result.completion_tokens,
    )

    log = RequestLog(
        api_key_id=api_key.id,
        virtual_model=body.model,
        provider_used=provider_name,
        fallback_triggered=fallback_triggered,
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

- [ ] **Step 6: Run the integration tests**

```bash
pytest src/tests/integration/test_fallback.py -v -m integration
```

Expected: 2 tests PASSED.

- [ ] **Step 7: Run the full test suite**

```bash
pytest src/tests/ -v
```

Expected: all tests PASSED (existing chat tests still pass because Ollama is priority 1).

- [ ] **Step 8: Type-check everything**

```bash
mypy src/prism/
```

Expected: `Success: no issues found`

- [ ] **Step 9: Commit**

```bash
git add alembic/versions/ src/prism/api/chat.py src/tests/integration/test_fallback.py
git commit -m "wire router into chat endpoint and seed fallback routes for openai and anthropic"
```

---

## Phase 2 Complete — Demo Gate

With `docker-compose up -d postgres redis` and `ollama serve` running:

```bash
# Normal request — hits Ollama (priority 1)
curl -s -X POST http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer <your-prism-key>" \
  -H "Content-Type: application/json" \
  -d '{"model": "fast", "messages": [{"role": "user", "content": "Say hello"}]}' \
  | python3 -m json.tool
# prism_metadata.provider_used should be "ollama", fallback_triggered false

# Stop Ollama to simulate failure
# (Ctrl+C the ollama serve process, or: pkill ollama)

# Same request — should now fall back to mock OpenAI
curl -s -X POST http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer <your-prism-key>" \
  -H "Content-Type: application/json" \
  -d '{"model": "fast", "messages": [{"role": "user", "content": "Say hello"}]}' \
  | python3 -m json.tool
# prism_metadata.provider_used should be "openai", fallback_triggered true

# Verify it was logged
docker-compose exec postgres psql -U prism -d prism \
  -c "SELECT provider_used, fallback_triggered, latency_ms FROM request_log ORDER BY created_at DESC LIMIT 5;"
```

**GitHub commit message for push:** `feat: Phase 2 — multi-provider routing, fallback chain, circuit breaker`

**Next:** Phase 3 — Presidio PII guardrails, injection heuristic, Redis exact cache, pgvector semantic cache.
