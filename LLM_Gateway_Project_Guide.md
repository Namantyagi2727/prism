
# Project Guide: "Conduit" — A Production LLM Gateway & Control Plane

*A complete build spec: architecture, tech stack, API contracts, phased roadmap, deployment, testing, and portfolio framing.*

Suggested names (pick one, or keep your own): **Conduit**, **Meridian Gateway**, **Aegis-LLM**, **Fluxgate**. This guide uses "Conduit" as a placeholder — find/replace as needed.

---

## 1. What This Project Is and Why It Matters

An LLM gateway is a proxy layer that sits between your applications and the LLM providers you actually use (OpenAI, Anthropic, a self-hosted model, etc.). Every company that scales past "one team calling OpenAI directly" ends up needing one, because uncontrolled LLM access creates five simultaneous problems: unpredictable cost, no visibility into failures, security exposure (prompt injection, PII leakage), no resilience when a provider degrades, and no way to compare or swap models without rewriting application code.

You are building a real, working version of this. Commercial products in this exact category — LiteLLM, Portkey, Helicone, Kong AI Gateway — are venture-funded because this problem is real and current. Building one yourself, understanding the tradeoffs, and being able to speak to *why* you made each decision is a stronger signal than another RAG chatbot demo.

This single project, built to spec, directly closes: Kubernetes, Terraform, Helm, CI/CD, model serving, observability (Prometheus/Grafana/OpenTelemetry), AI guardrails, Redis, secrets management, IAM, production FastAPI backend, authentication, and automated testing — nine to ten of the highest-priority gaps identified in your resume analysis, in one coherent, demoable system.

---

## 2. Requirements

### 2.1 Functional Requirements
- Expose an OpenAI-API-compatible endpoint (`/v1/chat/completions`, `/v1/embeddings`) so any existing client library works against Conduit with just a base-URL change.
- Route requests across at least three backends: OpenAI, Anthropic, and one self-hosted model served via vLLM.
- Support a configurable fallback chain per "virtual model" (e.g., `fast-cheap` → tries a small OpenAI model, falls back to Anthropic Haiku, falls back to local model).
- Issue and manage API keys per team/project, each with its own rate limit and monthly budget.
- Cache semantically similar requests to avoid redundant provider calls.
- Detect and block/redact PII and flag likely prompt-injection attempts before forwarding to a provider.
- Track token usage and computed cost per request, per key, per day.
- Emit traces, metrics, and structured logs for every request.
- Provide an admin API (and optionally a minimal dashboard) to view usage, cost, and error rates.

### 2.2 Non-Functional Requirements
- Added latency overhead from the gateway itself: target under 50ms p95 (excluding actual provider latency).
- Availability: gateway should degrade gracefully — if one provider is down, requests should fail over, not fail outright.
- This is a portfolio project, not a company system: design for correctness and clarity of demonstrated concepts over massive scale. Load-test to prove it *could* scale (thousands of req/min on a single node), not to prove it handles Google-scale traffic.
- Security: no plaintext secrets anywhere in the repo; API keys stored hashed; least-privilege IAM.

### 2.3 Constraints
- Solo builder, part-time (nights/weekends), realistic budget: a few dollars a day in AWS spend plus small API usage costs during testing — architect so you can tear down cloud resources between work sessions (Terraform makes this trivial).
- You already know Python, FastAPI basics, AWS Lambda/S3/DynamoDB, and Docker fundamentals — this project should build on that, not require learning a new language.
- Timeline target: 5–7 weeks part-time, compressible to ~3 weeks focused full-time (see Section 10).

---

## 3. High-Level Architecture

```
                         ┌─────────────────────────────────────────┐
                         │              Client Apps                 │
                         │   (any OpenAI-SDK-compatible caller)      │
                         └───────────────────┬───────────────────────┘
                                             │  HTTPS, API key in header
                                             ▼
                         ┌─────────────────────────────────────────┐
                         │            Conduit Gateway (FastAPI)      │
                         │                                            │
                         │  1. Auth middleware  (key lookup, rate     │
                         │     limit check, budget check)             │
                         │  2. Guardrail pre-check (PII, injection)   │
                         │  3. Semantic cache lookup (Redis/pgvector) │
                         │  4. Router (model → provider selection,    │
                         │     fallback chain, circuit breaker)       │
                         │  5. Provider call (w/ timeout + retry)     │
                         │  6. Guardrail post-check (response)        │
                         │  7. Cost calculator + usage logger         │
                         │  8. Cache writer                           │
                         │  9. OTel span close / metrics emit         │
                         └───┬───────────┬───────────┬───────────────┘
                             │           │           │
                 ┌───────────┘           │           └────────────┐
                 ▼                       ▼                        ▼
          ┌─────────────┐        ┌──────────────┐         ┌──────────────┐
          │   OpenAI    │        │  Anthropic   │         │  Self-hosted │
          │   API       │        │  API         │         │  vLLM server │
          └─────────────┘        └──────────────┘         └──────────────┘

          ┌─────────────┐        ┌──────────────┐         ┌──────────────┐
          │  Postgres   │        │    Redis     │         │ Prometheus + │
          │ (keys, teams,│        │ (cache,      │         │   Grafana +  │
          │ budgets,     │        │  rate-limit  │         │  OTel Collector
          │ audit log)   │        │  counters)   │         │              │
          └─────────────┘        └──────────────┘         └──────────────┘
```

### Component responsibilities

| Component | Responsibility |
|---|---|
| Auth middleware | Validates API key (hashed lookup), checks rate limit (Redis token bucket) and remaining budget (Postgres) |
| Guardrail engine | Pre-request: PII detection/redaction, prompt-injection heuristic score. Post-response: content filter |
| Semantic cache | Embeds prompt, checks Redis (exact) then pgvector (similarity) for a cached response within threshold |
| Router | Maps a requested "virtual model" name to a real provider+model, applies fallback chain |
| Circuit breaker | Tracks per-provider failure rate; opens circuit (stops sending traffic) after N failures in a window, half-opens after cooldown |
| Cost calculator | Uses a pricing table (per provider/model, $/1K tokens) to compute request cost from token counts |
| Usage logger | Writes request record to Postgres (key, model, tokens, cost, latency, cache hit/miss, status) |
| Observability | OpenTelemetry traces per request; Prometheus metrics (histograms/counters); structured JSON logs |
| Admin API | CRUD for keys/teams/budgets; read endpoints for usage/cost/error analytics |

---

## 4. Tech Stack (with justification)

| Layer | Choice | Why |
|---|---|---|
| Language | Python 3.12 | Matches your existing strength; async support is mature |
| Web framework | FastAPI | Async-native, automatic OpenAPI docs, Pydantic validation — the single best framework to deepen given your background |
| Validation | Pydantic v2 | Type-safe request/response models, fast |
| Primary DB | PostgreSQL 16 | Relational integrity for keys/budgets/audit log; also hosts pgvector — proof of "advanced SQL + production vector DB" in one system |
| ORM/migrations | SQLAlchemy 2.0 (async) + Alembic | Industry-standard; migrations are a concrete artifact recruiters can see in your repo |
| Cache & rate limiting | Redis 7 | Token-bucket rate limiting, exact-match cache, distributed locks |
| Vector similarity | pgvector extension on Postgres | Avoids a 4th datastore; still gives you real vector-DB experience |
| Providers | OpenAI SDK, Anthropic SDK, vLLM (self-hosted, OpenAI-compatible server) | Covers two major hosted APIs plus a real "model serving" component |
| Guardrails | Microsoft Presidio (PII), a lightweight prompt-injection classifier or heuristic+regex scorer | Both are realistic, resume-relevant tools, not hand-rolled toys |
| Tracing | OpenTelemetry SDK + Collector | Vendor-neutral, industry standard |
| Metrics | Prometheus client + Grafana dashboards | The most commonly requested monitoring stack in job postings you reviewed |
| Testing | pytest, pytest-asyncio, httpx.AsyncClient, testcontainers-python, Locust | Real integration tests against real Postgres/Redis instances, plus load testing |
| CI/CD | GitHub Actions | Lint (ruff) → type-check (mypy) → unit+integration tests → build Docker image → Trivy security scan → push to GHCR → deploy |
| Containerization | Docker (multi-stage build) | Small, reproducible images |
| Orchestration | Kubernetes — start local (kind or k3d), deploy real to AWS EKS (or ECS Fargate as a cheaper alternative — see tradeoffs in Section 11) | The single highest-priority missing skill on your gap list |
| Packaging | Helm chart | Standard way to package K8s manifests; another concrete resume artifact |
| IaC | Terraform (AWS provider) | Provisions VPC, EKS/ECS, RDS Postgres, ElastiCache Redis, IAM roles, ALB, Secrets Manager entries |
| Secrets | AWS Secrets Manager, injected via Kubernetes Secrets or External Secrets Operator | Never commit secrets; rotate via Terraform-managed policy |

---

## 5. Data Model

```sql
-- Teams / projects that own API keys
CREATE TABLE teams (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    monthly_budget_usd NUMERIC(10,2) NOT NULL DEFAULT 50.00,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- API keys (never store raw key — store a hash)
CREATE TABLE api_keys (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    team_id UUID NOT NULL REFERENCES teams(id),
    key_hash TEXT NOT NULL UNIQUE,
    key_prefix TEXT NOT NULL,        -- shown to user for identification, e.g. "cnd_ab12"
    rate_limit_rpm INT NOT NULL DEFAULT 60,
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at TIMESTAMPTZ
);

-- Model routing config
CREATE TABLE model_routes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    virtual_model TEXT NOT NULL,      -- e.g. "fast-cheap", "reasoning-heavy"
    priority INT NOT NULL,            -- order within fallback chain
    provider TEXT NOT NULL,           -- "openai" | "anthropic" | "vllm"
    real_model TEXT NOT NULL,         -- e.g. "gpt-4o-mini"
    timeout_ms INT NOT NULL DEFAULT 20000
);

-- Per-request usage log (this table is your evidence + your analytics source)
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
    guardrail_flag TEXT,              -- null | "pii_redacted" | "injection_suspected" | "blocked"
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Semantic cache index (pgvector)
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE prompt_cache (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    virtual_model TEXT NOT NULL,
    prompt_embedding VECTOR(1536),
    prompt_text TEXT NOT NULL,
    response_text TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX ON prompt_cache USING ivfflat (prompt_embedding vector_cosine_ops);
```

---

## 6. API Contract

### Client-facing (OpenAI-compatible)

```
POST /v1/chat/completions
Headers: Authorization: Bearer cnd_live_xxx
Body:
{
  "model": "fast-cheap",              // virtual model name, not a raw provider model
  "messages": [{"role": "user", "content": "..."}],
  "temperature": 0.7,
  "stream": false
}

Response: standard OpenAI chat completion shape, plus extra metadata:
{
  "id": "...",
  "choices": [...],
  "usage": {"prompt_tokens": .., "completion_tokens": .., "total_tokens": ..},
  "conduit_metadata": {
    "provider_used": "anthropic",
    "cache_hit": false,
    "fallback_triggered": true,
    "cost_usd": 0.00042,
    "latency_ms": 812
  }
}

POST /v1/embeddings   -- same pattern, embeddings passthrough
```

### Admin API

```
POST   /admin/teams                  create a team + budget
POST   /admin/keys                   issue a new API key for a team
DELETE /admin/keys/{id}               revoke a key
GET    /admin/usage?team_id=&range=   usage/cost time series
GET    /admin/routes                 view current routing config
PUT    /admin/routes                 update fallback chain config
```

### Operational

```
GET /healthz    liveness probe
GET /readyz     readiness probe (checks DB + Redis connectivity)
GET /metrics    Prometheus scrape endpoint
```

---

## 7. Deep Dive: Request Lifecycle

1. Request hits FastAPI, `Authorization` header extracted.
2. **Auth middleware**: hash the presented key, look up in Postgres (cache this lookup in Redis with short TTL to avoid a DB hit per request). Check `rate_limit_rpm` via a Redis token-bucket. Check remaining monthly budget. Any failure → 401/429 immediately, logged.
3. **Guardrail pre-check**: run PII detector (Presidio) over the prompt; redact or reject based on team policy. Run prompt-injection heuristic (keyword/pattern scoring, optionally a small classifier). Log a `guardrail_flag` if triggered.
4. **Cache lookup**: embed the prompt (small embedding model, cached client-side), check Redis for exact-match hash first (cheap), then pgvector cosine similarity above a configurable threshold (e.g. 0.95). On hit, skip straight to step 8.
5. **Routing**: look up `virtual_model` in `model_routes`, get ordered fallback chain. Check circuit breaker state for the top provider — if open, skip to next in chain.
6. **Provider call**: call with a hard timeout; on timeout/5xx, record failure against the circuit breaker and try the next provider in the chain. Exhausting the chain returns a clear 503 with which providers were tried.
7. **Guardrail post-check**: scan response for policy violations if configured.
8. **Cost + logging**: compute cost from token counts × pricing table, write `request_log` row.
9. **Cache write**: store prompt+response+embedding with a TTL (e.g. 24h, configurable per virtual model — some things should never be cached, like anything with `stream=true` or non-deterministic personalization).
10. **Observability**: close the OpenTelemetry span (with sub-spans for each step above), increment Prometheus counters/histograms, emit one structured JSON log line.

This lifecycle *is* your architecture diagram and your interview answer to "walk me through what happens when a request comes in" — memorize it.

---

## 8. Deep Dive: Caching Strategy

- Two-tier: Redis exact-match (hash of normalized prompt + model + params) for identical repeated requests, pgvector similarity for near-duplicate requests (paraphrases, minor edits).
- Cache key must include the virtual model and any params that affect output (temperature above ~0.3 should probably disable semantic caching entirely — document this as an explicit design decision, not an oversight).
- TTL strategy: short TTL (hours) by default; make it configurable per virtual model since some use cases (fast-cheap FAQ-style traffic) benefit from long caching and others (reasoning-heavy) should barely cache at all.
- Track and expose cache hit rate as a headline metric — this is one of your best "cost savings" talking points.

---

## 9. Deep Dive: Routing, Fallback, and Circuit Breaker

- Fallback chain is config-driven (the `model_routes` table), not hardcoded — this is what lets you demo "swap providers with zero code changes."
- Circuit breaker pattern: closed (normal) → after N failures in a rolling window, open (stop sending, fail fast to next provider) → after a cooldown, half-open (allow one test request) → closed again if it succeeds. Implement with a small state machine (a library like `pybreaker` is fine, or roll your own — rolling your own for one component is a good interview talking point about understanding the pattern, not just importing it).
- Retries: only retry idempotent-safe failures (timeouts, 5xx, connection errors) — never blindly retry on ambiguous errors that might have already generated a billable completion.

---

## 10. Deep Dive: Guardrails

- PII: use Presidio's built-in recognizers (email, phone, SSN, credit card, etc.) against the prompt before it leaves your infrastructure. Decide and document a policy: redact-and-forward vs. block-and-reject.
- Prompt injection: start with a heuristic scorer (phrases like "ignore previous instructions", encoded/obfuscated payloads, unusual instruction density) — this is honest, explainable, and good enough for a portfolio project. Note in your README that a production system would add an LLM-as-judge classifier or a fine-tuned detector as a next step — showing you know the limits of your own heuristic is itself a strong signal.
- Everything guardrail-related gets logged with a reason code — this feeds your "AI safety" resume bullet and is exactly what the earlier gap analysis flagged as missing evidence.

---

## 11. Deep Dive: Observability

- **Tracing**: instrument with OpenTelemetry, one root span per request, child spans for auth/guardrail/cache/provider-call. Export to an OTel Collector, visualize with Jaeger or Grafana Tempo.
- **Metrics**: Prometheus counters (requests_total by provider/status), histograms (latency_ms by provider, cache lookup time), gauges (circuit breaker state per provider). Build 2–3 Grafana dashboards: (1) traffic & errors, (2) cost & cache hit rate, (3) provider health/circuit breaker state.
- **Logging**: structured JSON logs (one line per request) to stdout — in a real deploy this would ship to CloudWatch Logs or Loki. Redact prompt/response content by default; make full-content logging an explicit opt-in per team (another good security-mindedness talking point).

---

## 12. Scale & Reliability Notes (what you'd revisit as this grows)

Per the system-design framework: be explicit about what's out of scope now and what you'd change if this were a real company system at 100x the load.

- **Now**: single FastAPI instance (or a few replicas), single Postgres primary, single Redis instance — fine for a portfolio-scale load test (hundreds to low-thousands of req/min).
- **At real scale you'd add**: read replicas for Postgres analytics queries, Redis Cluster instead of single-node, horizontal pod autoscaling in K8s keyed on request latency/queue depth, a message queue (e.g., SQS or Kafka) if you wanted to decouple logging/cost-calculation from the hot request path, and a dedicated rate-limiting service if multi-region.
- **Failure domains**: document what happens if Postgres is down (auth fails closed — no key validation, no requests served — a deliberate, defensible choice you should state in the README) vs. Redis down (degrade gracefully — skip caching, fall back to DB-only rate limiting, log a warning).
- State this explicitly in your README under a "Scaling this further" section — interviewers specifically probe for whether you understand the limits of what you built, and calling it out yourself pre-empts the question.

---

## 13. Security Considerations

- API keys: generate with high entropy, store only a salted hash (never raw) — same principle as password storage.
- Secrets (provider API keys, DB credentials): AWS Secrets Manager in production, `.env` + `.gitignore` locally, never committed. Terraform provisions the Secrets Manager entries; Kubernetes reads them via Secrets or External Secrets Operator.
- Least-privilege IAM: the gateway's IAM role should only have the specific permissions it needs (Secrets Manager read, CloudWatch write) — write this out explicitly in your Terraform and be ready to explain it.
- TLS everywhere (ALB terminates TLS in front of the cluster).
- Rate limiting doubles as a basic abuse/DoS mitigation.
- Audit log: every admin action (key creation/revocation, route changes) gets its own log entry with actor and timestamp.

---

## 14. Testing Strategy

| Test type | Tooling | What it covers |
|---|---|---|
| Unit tests | pytest | Cost calculator, router logic, circuit breaker state transitions, guardrail scoring functions — all pure logic, no I/O |
| Integration tests | pytest-asyncio + httpx.AsyncClient + testcontainers | Spin up real Postgres + Redis containers in CI, hit real endpoints, assert on DB state and responses |
| Contract tests | Custom fixtures | Verify your `/v1/chat/completions` response shape matches the OpenAI spec closely enough that the real `openai` Python client works against it unmodified |
| Load tests | Locust | Simulate multiple teams hitting rate limits simultaneously, measure gateway-added latency under concurrency, find the breaking point |
| Chaos test | Manual or scripted | Kill the mock provider mid-test, confirm fallback and circuit breaker behave correctly |

Wire unit + integration tests into GitHub Actions so every PR runs the full suite against ephemeral containers — this is your strongest "automated testing" and "CI/CD ownership" evidence in one workflow file.

---

## 15. Repository Structure

```
conduit/
├── src/
│   ├── conduit/
│   │   ├── api/
│   │   │   ├── chat.py            # /v1/chat/completions route
│   │   │   ├── embeddings.py
│   │   │   ├── admin.py
│   │   │   └── health.py
│   │   ├── core/
│   │   │   ├── auth.py            # key validation, rate limiting
│   │   │   ├── router.py          # model routing + fallback chain
│   │   │   ├── circuit_breaker.py
│   │   │   ├── cache.py           # Redis + pgvector semantic cache
│   │   │   ├── guardrails.py      # PII + injection checks
│   │   │   └── cost.py            # pricing tables + cost calc
│   │   ├── providers/
│   │   │   ├── openai_provider.py
│   │   │   ├── anthropic_provider.py
│   │   │   └── vllm_provider.py
│   │   ├── db/
│   │   │   ├── models.py          # SQLAlchemy models
│   │   │   └── session.py
│   │   ├── observability/
│   │   │   ├── tracing.py
│   │   │   ├── metrics.py
│   │   │   └── logging.py
│   │   ├── config.py
│   │   └── main.py                # FastAPI app entrypoint
│   └── tests/
│       ├── unit/
│       ├── integration/
│       └── load/
│           └── locustfile.py
├── alembic/                        # DB migrations
├── deploy/
│   ├── docker/
│   │   └── Dockerfile
│   ├── helm/
│   │   └── conduit/
│   └── terraform/
│       ├── main.tf
│       ├── vpc.tf
│       ├── eks.tf                  # or ecs.tf
│       ├── rds.tf
│       ├── elasticache.tf
│       ├── secrets.tf
│       ├── iam.tf
│       └── variables.tf
├── .github/
│   └── workflows/
│       └── ci.yml
├── docker-compose.yml               # local dev: postgres + redis + conduit
├── pyproject.toml
├── README.md                        # your case study — see Section 19
└── .env.example
```

---

## 16. Phased Build Roadmap

**Phase 0 — Setup (2–3 days)**
Repo scaffold, `uv` or Poetry environment, pre-commit hooks (ruff, mypy), `docker-compose.yml` with Postgres + Redis, bare FastAPI app with a health check. *Gate: `docker-compose up` gives you a running skeleton.*

**Phase 1 — Core single-provider proxy (Week 1)**
OpenAI-compatible `/v1/chat/completions` passthrough to OpenAI only. API key issuance and auth middleware. Request logging to Postgres. *Gate: you can call Conduit with the real `openai` Python client by only changing `base_url`.*

**Phase 2 — Multi-provider routing (Week 2)**
Add Anthropic and a self-hosted vLLM instance. Build `model_routes` config + fallback chain logic + circuit breaker. *Gate: killing your local vLLM mid-demo causes automatic fallback to Anthropic, visibly, without a code change.*

**Phase 3 — Guardrails + caching (Week 3)**
Presidio PII detection, injection heuristic scorer, Redis exact-cache, pgvector semantic cache. *Gate: sending the same question twice shows a cache hit with near-zero latency and $0 cost; sending an obvious injection attempt gets flagged and logged.*

**Phase 4 — Observability (Week 4)**
OpenTelemetry tracing, Prometheus metrics, 2–3 Grafana dashboards. *Gate: you can open Grafana during a live demo and watch latency/cost/cache-hit-rate update in real time as you send requests.*

**Phase 5 — Testing + CI (Week 5)**
Full pytest suite (unit + integration via testcontainers), GitHub Actions pipeline (lint → type-check → test → build → Trivy scan). *Gate: a broken PR fails the pipeline before it can merge; you can point to a real Actions run.*

**Phase 6 — Containerize + deploy for real (Week 6)**
Dockerfile, Helm chart, Terraform provisioning EKS (or ECS Fargate — see Section 11 for the tradeoff), RDS, ElastiCache, Secrets Manager, IAM. Deploy, get a real URL. *Gate: `terraform apply` stands up the whole stack from scratch; `terraform destroy` tears it down cleanly (do this between work sessions to control cost).*

**Phase 7 — Polish + portfolio packaging (Week 7)**
Locust load test with real numbers, a short admin analytics view (a simple server-rendered page or even a clean Streamlit view is fine here — it's an internal tool, not the star of the show), architecture diagram, a tight README case study, a 2–3 minute demo recording.

Total: **5–7 weeks part-time**, compressible to roughly **3 weeks** if worked full-time.

---

## 17. Trade-off Analysis (explicit, per system-design framework)

| Decision | Choice made | Alternative | Why |
|---|---|---|---|
| Orchestration | Kubernetes (EKS) | ECS Fargate | K8s is the higher-value skill for your gap list and more universally requested; ECS is cheaper/simpler to run but a weaker resume signal. If cost is a real concern, build and demo on local `kind`/`k3d` and only stand up EKS briefly for the final recording, then tear down. |
| Vector store | pgvector on existing Postgres | Standalone Pinecone/Weaviate | Avoids a 4th moving part; still proves "production vector DB" competence. Mention in your README that swapping in a managed vector DB is a one-file change — showing you understand the abstraction matters more than which one you picked. |
| Circuit breaker | Hand-rolled state machine | `pybreaker` library | Rolling your own for this one component (and only this one) is a deliberate choice to prove you understand the pattern, not just how to import it. Everywhere else, use standard libraries — don't reinvent auth or crypto. |
| Prompt-injection detection | Heuristic scorer | Fine-tuned classifier / LLM-as-judge | Heuristic is honest about its limits and fast to ship; explicitly document it as "v1" with a named upgrade path — this reads as maturity, not laziness. |
| Admin UI | Minimal server-rendered page or Streamlit | Full React dashboard | The dashboard is not the point of this project — don't let it eat your timeline. If you also want React practice, that's a separate, smaller project. |

---

## 18. Metrics to Capture (for your README and interviews)

Run the Locust load test and the demo scenarios, then report real numbers — not estimates:
- p50 / p95 / p99 latency added by the gateway itself (isolate this from provider latency).
- Cache hit rate (%) and estimated $ saved per 1,000 requests at that hit rate.
- Error rate with vs. without the fallback chain enabled (simulate a provider outage both ways).
- Throughput ceiling on a single instance before latency degrades (from your Locust run).
- Cost accuracy: computed cost vs. actual provider invoice for a test batch — validates your cost calculator is correct, not just present.

These numbers are the difference between "I built an LLM gateway" and "I built an LLM gateway that added 8ms p95 overhead, hit a 34% cache rate saving an estimated $X/1000 requests, and kept error rate at 0.2% during a simulated provider outage via automatic fallback." The second version is what gets remembered.

---

## 19. README / Case Study Structure

Your README is a deliverable in its own right — many reviewers will read it before they read any code.

1. One-paragraph pitch + architecture diagram.
2. "Why I built this" — tie it explicitly to the real problem (cost/reliability/safety of ungoverned LLM access).
3. Architecture walkthrough (reuse Section 3 and 7 above).
4. Key design decisions and tradeoffs (reuse Section 17).
5. Benchmarks (Section 18's real numbers).
6. How to run it locally (`docker-compose up`) and how to deploy it (`terraform apply`).
7. What I'd do next / how this would need to change at 100x scale (Section 12) — this single section signals seniority beyond your years of experience.

---

## 20. Resume Bullets and Interview Narrative

**Resume bullets (adapt with your real numbers once built):**
- "Designed and deployed a multi-provider LLM gateway (FastAPI, Kubernetes, Terraform) implementing automatic failover, semantic caching, and prompt-injection/PII guardrails; reduced redundant provider calls by [X]% via a two-tier caching layer."
- "Built full observability (OpenTelemetry, Prometheus, Grafana) into a production AI service, enabling real-time cost, latency, and error-rate tracking per team; instrumented CI/CD with automated unit/integration testing and container security scanning via GitHub Actions."
- "Provisioned all cloud infrastructure (EKS, RDS, ElastiCache, IAM, Secrets Manager) as code with Terraform, enabling reproducible environment teardown/rebuild and eliminating manual cloud console configuration."

**STAR-style interview narrative:**
*Situation*: LLM usage at most companies is ungoverned — no cost visibility, no failover, no safety checks.
*Task*: build a real gateway that solves all four at once, not a toy demo.
*Action*: walk through the request lifecycle (Section 7), the circuit breaker/fallback design, and one specific hard decision (e.g., why heuristic injection detection over a classifier, or why pgvector over a dedicated vector DB) — this is where you demonstrate judgment, not just execution.
*Result*: give your real Section 18 numbers, and name the one thing you'd change at 100x scale.

---

## 21. Stretch Goals (only after the core is solid)

- Streaming response support (SSE) with correct cost accounting on partial streams.
- Slack/email budget-alert webhooks when a team approaches its monthly cap.
- Canary rollout of routing config changes (shift 10% of traffic to a new fallback chain, auto-rollback on error-rate spike).
- Hook in the RAG/agent evaluation framework from your other project idea to score live responses for groundedness, turning Conduit into an eval-aware gateway — this is the natural "combine two portfolio projects" move if you build both.
- Per-team model allow-lists (a governance feature real enterprises ask for).

---

## 22. Learning Resources by Gap

- **FastAPI**: official docs' "Async" and "Dependencies" sections — you already know basics, focus on middleware and background tasks.
- **Kubernetes**: start with `kind` locally, follow the official "Deployments, Services, ConfigMaps, Secrets" walkthrough before touching EKS.
- **Terraform**: HashiCorp's official AWS provider tutorials; write the VPC/EKS/RDS modules yourself rather than copying a template, even if it's slower — the understanding is the point.
- **OpenTelemetry**: the Python "getting started" guide plus the FastAPI auto-instrumentation package.
- **Circuit breaker pattern**: read the pattern description (Martin Fowler's write-up) before implementing — you want to explain *why* it works, not just that it does.
- **pgvector**: the extension's own README has everything needed for cosine-similarity search at this scale.

---

*This document is meant to be a living spec — update Section 17 (tradeoffs) and Section 18 (metrics) as you actually build, since those two sections are what make the finished README credible instead of generic.*
