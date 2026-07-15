# Prism — Architecture

Two views of the system: how a single request flows through the gateway, and
how the pieces are deployed together.

## Request Flow

Every call to `/v1/chat/completions` passes through the same pipeline. Two
paths exit early — a guardrail block and an exact-cache hit — both skipping
the provider call (and its cost) entirely.

```mermaid
flowchart TD
    Client(["Client<br/>(openai SDK, base_url=prism)"]) -->|"POST /v1/chat/completions"| Auth

    Auth["Auth<br/>hash key + Redis per-minute rate limit"] -->|invalid/revoked key| Reject401(["401 Unauthorized"])
    Auth -->|over rate limit| Reject429(["429 Rate Limited"])
    Auth -->|ok| Guardrail

    Guardrail["Guardrail pre-check<br/>Presidio PII scan + injection heuristic"] -->|flagged| Block(["400 Blocked<br/>+ logged with reason"])
    Guardrail -->|clean| CacheLookup

    CacheLookup{"Exact cache hit?<br/>Redis, SHA-256(model+messages+temperature)"}
    CacheLookup -->|yes| CacheHit(["200 Response<br/>cache_hit=true, cost=$0"])
    CacheLookup -->|no| Router

    Router["Router<br/>priority-ordered fallback chain + circuit breaker"] --> Provider
    Provider["Provider call<br/>Ollama / OpenAI-mock / Anthropic-mock"]
    Provider -->|success| CostLog
    Provider -->|failure, provider marked, try next in chain| Router
    Provider -->|all providers exhausted| Reject503(["503 All providers failed"])

    CostLog["Cost calc (token count × price table)<br/>+ write request_log row"] --> CacheWrite
    CacheWrite["Cache write<br/>Redis exact, 1h TTL"] --> Response(["200 Response<br/>+ prism_metadata block"])
```

**Notes:**
- The circuit breaker (closed/open/half-open, threshold 3 failures, 30s
  cooldown) sits inside the Router step — an open circuit for a provider
  skips straight to the next one in the chain without attempting the call.
- `prism_metadata` on every response reports `provider_used`, `cache_hit`,
  `fallback_triggered`, `cost_usd`, and `latency_ms` — this is what the
  admin dashboard's Overview/Performance/Safety tabs aggregate.
- `cache.py` also defines a semantic (pgvector cosine-similarity) cache
  tier, but it isn't currently called from the chat endpoint — only the
  exact-match Redis cache shown above is live in the request path.

## Infrastructure Topology

Everything except Ollama runs in `docker-compose`. Ollama runs on the host
(Metal-accelerated on Apple Silicon) — the app reaches it over the network
like any other provider, which is why it's drawn outside the compose
boundary.

```mermaid
graph LR
    subgraph host["Host machine"]
        Ollama["Ollama<br/>llama3.2:3b"]
    end

    subgraph compose["docker-compose"]
        App["app<br/>FastAPI / Prism"]
        Postgres[("postgres<br/>+ pgvector")]
        Redis[("redis")]
        Jaeger["jaeger<br/>trace UI"]
        Prometheus["prometheus<br/>metrics scrape"]
        Grafana["grafana<br/>dashboards"]
    end

    App -->|SQL, asyncpg| Postgres
    App -->|cache + rate limit| Redis
    App -->|OTLP spans| Jaeger
    App -.->|chat + embeddings, HTTP| Ollama
    Prometheus -->|scrape /metrics/ every 15s| App
    Grafana -->|query| Prometheus
```

**Notes:**
- `app` depends on `postgres`, `redis`, and `jaeger` being healthy before it
  starts (`docker-compose.yml` healthchecks); `prometheus` depends on `app`;
  `grafana` depends on `prometheus` and comes with the Prism dashboard
  auto-provisioned.
- The admin dashboard (`/admin/dashboard`) queries `postgres` directly — it
  isn't a separate service, just another route on `app`.
