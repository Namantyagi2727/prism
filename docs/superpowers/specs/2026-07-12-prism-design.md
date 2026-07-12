# Prism — LLM Gateway Design Spec

**Date:** 2026-07-12  
**Status:** Approved  
**Goal:** Portfolio project demonstrating Kubernetes, Terraform, CI/CD, observability, guardrails, Redis, FastAPI, auth, and automated testing — all in one coherent, demoable system.

---

## 1. What We're Building

Prism is a production-grade LLM gateway: a proxy layer that sits between client applications and LLM providers (Ollama, OpenAI, Anthropic). It handles auth, rate limiting, cost tracking, semantic caching, PII/injection guardrails, multi-provider routing with fallback, and full observability.

Any app using the standard OpenAI Python SDK can point `base_url` at Prism with zero other code changes.

---

## 2. Constraints & Decisions

| Topic | Decision |
|---|---|
| Name | **Prism** |
| Deployment | Local only (Docker Compose + kind) — cloud deferred |
| Self-hosted model | **Ollama** (not vLLM) — runs via Metal on M4 Pro, OpenAI-compatible API |
| OpenAI / Anthropic | Mock providers for now — real keys added later |
| Admin UI | Minimal — not the focus |
| Kubernetes | kind locally — deferred until after core is solid |
| Secrets | `.env` locally, never committed |
| GitHub | User pushes; Claude provides commands only |

---

## 3. Architecture

```
Client (openai SDK, base_url=http://localhost:8000)
  │
  ▼
FastAPI (Prism)
  1. Auth middleware      → hash key, check rate limit (Redis token bucket), check budget (Postgres)
  2. Guardrail pre-check  → PII redaction (Presidio), injection heuristic score
  3. Cache lookup         → Redis exact hash → pgvector cosine similarity
  4. Router               → virtual model → fallback chain → circuit breaker check
  5. Provider call        → Ollama / mock OpenAI / mock Anthropic (timeout + retry)
  6. Guardrail post-check → content filter on response
  7. Cost + logging       → token count × price table → write request_log row
  8. Cache write          → store embedding + response with TTL
  9. OTel span close      → Prometheus metrics emit + structured JSON log
  │
  ▼
Response (OpenAI-compatible shape + prism_metadata block)
```

### Component Responsibilities

| Component | Responsibility |
|---|---|
| Auth middleware | Validates API key (hashed lookup in Postgres, short-TTL Redis cache), checks rate limit (Redis token bucket), checks monthly budget |
| Guardrail engine | Pre-request: PII detection/redaction via Presidio, injection heuristic scorer. Post-response: content filter |
| Semantic cache | Redis exact-match (hash of normalized prompt+model+params), then pgvector cosine similarity (threshold: 0.95) |
| Router | Maps virtual model name → ordered fallback chain from `model_routes` table |
| Circuit breaker | Hand-rolled state machine: closed → open (after N failures in window) → half-open (after cooldown) → closed |
| Cost calculator | Token counts × per-provider pricing table → cost_usd per request |
| Usage logger | Writes one `request_log` row per request — the evidence layer for all resume claims |
| Observability | OTel root span per request with child spans per step; Prometheus counters/histograms; structured JSON logs |
| Admin API | CRUD for teams/keys/budgets; usage analytics endpoints |

---

## 4. Data Model

```sql
-- Teams own API keys and have monthly budgets
CREATE TABLE teams (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    monthly_budget_usd NUMERIC(10,2) NOT NULL DEFAULT 50.00,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- API keys — raw key never stored, only a hash
CREATE TABLE api_keys (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    team_id UUID NOT NULL REFERENCES teams(id),
    key_hash TEXT NOT NULL UNIQUE,
    key_prefix TEXT NOT NULL,
    rate_limit_rpm INT NOT NULL DEFAULT 60,
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at TIMESTAMPTZ
);

-- Virtual model → provider fallback chain config
CREATE TABLE model_routes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    virtual_model TEXT NOT NULL,
    priority INT NOT NULL,
    provider TEXT NOT NULL,   -- "ollama" | "openai" | "anthropic"
    real_model TEXT NOT NULL,
    timeout_ms INT NOT NULL DEFAULT 20000
);

-- One row per request — all analytics and cost tracking lives here
CREATE TABLE request_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    api_key_id UUID NOT NULL REFERENCES api_keys(id),
    virtual_model TEXT NOT NULL,
    provider_used TEXT NOT NULL,
    fallback_triggered BOOLEAN NOT NULL DEFAULT false,
    cache_hit BOOLEAN NOT NULL DEFAULT false,
    prompt_tokens INT,
    completion_tokens INT,
    cost_usd NUMERIC(10,6),
    latency_ms INT,
    status_code INT,
    guardrail_flag TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Semantic cache with pgvector
CREATE EXTENSION IF NOT EXISTS vector;
-- Note: embedding dimension is 768 (nomic-embed-text via Ollama, no OpenAI key needed)
CREATE TABLE prompt_cache (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    virtual_model TEXT NOT NULL,
    prompt_embedding VECTOR(768),
    prompt_text TEXT NOT NULL,
    response_text TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX ON prompt_cache USING ivfflat (prompt_embedding vector_cosine_ops);
```

---

## 5. API Contract

### Client-facing (OpenAI-compatible)

```
POST /v1/chat/completions
Authorization: Bearer prism_live_xxx

Body: standard OpenAI chat completions request, model = virtual model name (e.g. "fast")

Response: standard OpenAI shape + prism_metadata:
{
  "choices": [...],
  "usage": {...},
  "prism_metadata": {
    "provider_used": "ollama",
    "cache_hit": false,
    "fallback_triggered": false,
    "cost_usd": 0.00042,
    "latency_ms": 312
  }
}

POST /v1/embeddings   (passthrough, same pattern)
```

### Admin API

```
POST   /admin/teams
POST   /admin/keys
DELETE /admin/keys/{id}
GET    /admin/usage?team_id=&range=
GET    /admin/routes
PUT    /admin/routes
```

### Operational

```
GET /healthz   liveness
GET /readyz    readiness (checks Postgres + Redis)
GET /metrics   Prometheus scrape
```

---

## 6. Phase Map

| Phase | Focus | Demo Gate | Git Commit |
|---|---|---|---|
| 0 | Repo scaffold, pyproject.toml, ruff+mypy hooks, Docker Compose (Postgres+Redis), bare FastAPI + healthz/readyz | `docker-compose up` → healthcheck 200 | `feat: Phase 0 — project scaffold and dev environment` |
| 1 | Ollama provider, `/v1/chat/completions` passthrough, API key auth + rate limiting, Alembic migrations, request logging | Real request → Ollama → response logged in DB | `feat: Phase 1 — core proxy with Ollama, auth, and request logging` |
| 2 | Mock OpenAI + Anthropic providers, model_routes config, fallback chain, circuit breaker | Kill Ollama → automatic fallback, logged | `feat: Phase 2 — multi-provider routing, fallback chain, circuit breaker` |
| 3 | Presidio PII, injection heuristic, Redis exact cache, pgvector semantic cache | Same question twice → cache hit, $0 cost; injection flagged | `feat: Phase 3 — guardrails and two-tier semantic caching` |
| 4 | OTel tracing, Prometheus metrics, Grafana dashboards | Live Grafana updating during requests | `feat: Phase 4 — full observability stack` |
| 5 | pytest unit + integration (testcontainers), GitHub Actions CI | Broken PR fails CI; real Actions run visible | `feat: Phase 5 — test suite and CI/CD pipeline` |
| 6 | Locust load test, admin analytics, README, demo recording | Published README with real benchmark numbers | `feat: Phase 6 — load testing, polish, and portfolio packaging` |

---

## 7. Tech Stack

| Layer | Choice |
|---|---|
| Language | Python 3.12 |
| Framework | FastAPI (async) |
| Validation | Pydantic v2 |
| DB | PostgreSQL 16 + pgvector |
| ORM / migrations | SQLAlchemy 2.0 async + Alembic |
| Cache + rate limiting | Redis 7 |
| Providers | Ollama (real), OpenAI mock, Anthropic mock |
| Guardrails | Microsoft Presidio (PII), heuristic injection scorer |
| Tracing | OpenTelemetry + Collector + Jaeger |
| Metrics | Prometheus + Grafana |
| Testing | pytest, pytest-asyncio, httpx.AsyncClient, testcontainers-python, Locust |
| CI/CD | GitHub Actions |
| Containers | Docker multi-stage + Docker Compose |
| Linting | ruff + mypy |

---

## 8. Repository Structure

```
prism/
├── src/
│   ├── prism/
│   │   ├── api/           # chat.py, embeddings.py, admin.py, health.py
│   │   ├── core/          # auth.py, router.py, circuit_breaker.py, cache.py, guardrails.py, cost.py
│   │   ├── providers/     # ollama_provider.py, openai_provider.py, anthropic_provider.py
│   │   ├── db/            # models.py, session.py
│   │   ├── observability/ # tracing.py, metrics.py, logging.py
│   │   ├── config.py
│   │   └── main.py
│   └── tests/
│       ├── unit/
│       ├── integration/
│       └── load/locustfile.py
├── alembic/
├── deploy/
│   ├── docker/Dockerfile
│   └── helm/prism/        # stretch goal
├── .github/workflows/ci.yml
├── docker-compose.yml
├── pyproject.toml
├── README.md
└── .env.example
```

---

## 9. Scaling Notes (for README)

**Now:** single FastAPI instance, single Postgres, single Redis — sufficient for load test demonstrating thousands of req/min on one node.

**At 100x scale:** read replicas for Postgres analytics queries, Redis Cluster, HPA in K8s keyed on latency/queue depth, SQS/Kafka to decouple logging from hot path, dedicated rate-limiting service for multi-region.

**Failure modes (explicit):**
- Postgres down → auth fails closed (no requests served) — deliberate, defensible
- Redis down → degrade gracefully: skip cache, fall back to DB-only rate limiting, log warning

---

## 10. Security

- API keys: high-entropy generation, store only salted hash (never raw)
- Secrets: `.env` locally + `.gitignore`; never committed
- Audit log: every admin action logged with actor + timestamp
- Rate limiting doubles as basic DoS mitigation
- Prompt/response content redacted from logs by default; opt-in per team
