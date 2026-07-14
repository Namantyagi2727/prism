# Locust Load Test — Design Spec

**Date:** 2026-07-14
**Status:** Approved
**Goal:** Phase 6, sub-project 2 of 4 (admin dashboard ✅ → **Locust load test** → architecture diagram → README case study). Produce the real numbers the project guide's Section 18 wants: gateway-overhead p50/p95/p99 latency isolated from provider latency, cache hit rate + estimated $ saved, error rate with vs. without fallback, and throughput ceiling — backed by an actual load run, not estimates.

---

## 1. What We're Building

A Locust load test (`src/tests/load/locustfile.py`) plus a small companion migration and a run-procedure doc. Two `HttpUser` classes:

- **`GatewayOverheadUser`** — high concurrency, hits a new `mock-fast` virtual model (routed only to the openai mock, no Ollama in the chain) with a realistic traffic mix. Isolates the gateway's own overhead (auth, guardrail scan, cache lookup/write, routing, logging) from any real inference latency.
- **`RealInferenceUser`** — low concurrency, hits the existing `fast` virtual model (real Ollama → mock fallbacks) for realistic end-to-end numbers.

Both share one setup-created API key with a raised rate limit, and a fixed pool of pre-verified-safe prompts (never randomly generated text) to avoid corrupting results with guardrail false positives.

---

## 2. Constraints & Decisions

| Topic | Decision |
|---|---|
| Scope | Two scenarios: isolated gateway overhead (mocks) + isolated realistic (real Ollama). Not real-Ollama-only, not mocks-only. |
| Mock routing | New Alembic migration seeds a `mock-fast` virtual model → `(openai, gpt-4o-mini)` priority 1, no other providers. Existing `fast` model is untouched. |
| Outage/fallback comparison | Manual two-run procedure, documented, not automated. Run 1: normal. Run 2: `ollama serve` stopped (or `OLLAMA_BASE_URL` pointed at an unreachable port + app restarted). Compare error rates from the two Locust reports. |
| Traffic mix (`GatewayOverheadUser`) | Weighted tasks: 70% cache-miss, 20% cache-hit (repeat prompt), 10% guardrail-block (PII prompt) |
| Uniqueness source | `temperature` (a float, part of the exact-cache key, never guardrail-scanned) — not random text in message content. See Global Constraints. |
| Rate limiting | Setup creates one API key via `/admin/teams` + `/admin/keys` with `rate_limit_rpm` set high (100000) — otherwise the existing 60 RPM default throttles the run almost immediately and the numbers measure the rate limiter, not the gateway. |
| Reporting | Locust's own `--html` report for latency/RPS. Cache-hit-rate and cost-per-1000 pulled separately from `/admin/dashboard` (built in the previous sub-project) after each run — not Locust-native metrics. |
| Run modes | Three invocations documented: `GatewayOverheadUser` only, `RealInferenceUser` only, both together (default, for the "throughput ceiling" combined number) |

---

## 3. New Migration: `mock-fast` Virtual Model

There is currently no admin API to create `ModelRoute` rows at runtime — routes are seeded only via Alembic migrations (see `32feb0b2b4ed_seed_fallback_routes.py`, which seeded `fast`'s openai/anthropic fallback rows). A new migration follows the same pattern:

```python
op.execute(
    "INSERT INTO model_routes "
    "(id, virtual_model, priority, provider, real_model, timeout_ms) VALUES "
    f"('{uuid.uuid4()}', 'mock-fast', 1, 'openai', 'gpt-4o-mini', 10000)"
)
```

Single route, priority 1, no fallback chain needed — the mock provider is deterministic and never fails, so there's nothing to fall back from. Downgrade deletes the `mock-fast` rows, mirroring the existing migration's downgrade pattern.

---

## 4. Locustfile Structure

### Shared setup (`@events.test_start` listener)
Runs once when Locust starts (not per simulated user): creates one team (`loadtest-<uuid8>`) and one API key via the existing admin endpoints, with `rate_limit_rpm=100000`. The resulting raw key is stored in a module-level dict and read by every user's requests.

### Shared safe-prompt pool
A fixed list of ~6 plain factual questions (e.g. "What is the capital of France?", "What year did the Berlin Wall fall?") — verified once via `scan_prompt()` to never trigger the guardrail, matching the fix already applied to `test_metrics_endpoint.py` and `test_admin_dashboard.py` this session. One additional fixed PII-triggering prompt for the guardrail-block task.

### `GatewayOverheadUser(PrismUser)`
- `weight = 9`, `wait_time = between(0.01, 0.1)` (high concurrency)
- `@task(70) cache_miss` — random safe prompt + `temperature=random.random()` → guaranteed fresh cache key, hits `mock-fast`
- `@task(20) cache_hit` — fixed prompt + `temperature=0.0` → same cache key every call, hits the exact cache after the first
- `@task(10) guardrail_block` — fixed PII prompt, expects `400`

### `RealInferenceUser(PrismUser)`
- `weight = 1`, `wait_time = between(2, 5)` (low concurrency — real inference is ~2s/request; this keeps Ollama from being overwhelmed while still contributing realistic mixed load)
- `@task real_chat` — random safe prompt + unique `temperature`, hits `fast` (real Ollama)

### Shared base (`PrismUser`, `abstract = True`)
A `_chat(content, model, temperature)` helper wrapping `self.client.post(...)` with the shared API key header and a Locust `name=` grouping tag so mock vs. real-inference requests report as separate lines in Locust's stats table even though they hit the same URL path.

---

## 5. Run Procedure (documented in `src/tests/load/README.md`)

1. **Prerequisites:** `docker-compose up -d` (postgres, redis, app), `ollama serve` running with `llama3.2:3b` pulled, migrations applied (including the new `mock-fast` seed).
2. **Gateway overhead only:**
   `locust -f src/tests/load/locustfile.py GatewayOverheadUser --host http://localhost:8000 --users 50 --spawn-rate 10 --run-time 2m --headless --html src/tests/load/reports/overhead.html`
3. **Realistic (real Ollama) only:**
   `locust -f src/tests/load/locustfile.py RealInferenceUser --host http://localhost:8000 --users 5 --spawn-rate 1 --run-time 2m --headless --html src/tests/load/reports/realistic.html`
4. **Combined (throughput ceiling number):**
   `locust -f src/tests/load/locustfile.py --host http://localhost:8000 --users 50 --spawn-rate 10 --run-time 2m --headless --html src/tests/load/reports/combined.html`
5. **Outage comparison:** stop `ollama serve`, re-run step 4, compare error rates and `fallback_triggered` counts (via `/admin/dashboard`'s Performance tab) between the two combined runs.
6. After each run, check `/admin/dashboard` (Basic Auth) for cache-hit-rate and cost-by-team numbers to fold into the README's benchmark table (the next sub-project).

`src/tests/load/reports/` is gitignored (generated artifacts, not source).

---

## 6. Error Handling

- If the setup listener's admin calls fail (e.g., app not running), Locust should fail fast with a clear error rather than every simulated user separately failing auth — the listener raises if team/key creation doesn't return 2xx.
- `guardrail_block` task expects `400` and asserts on it via Locust's `catch_response` context manager, marking it a Locust failure if the response is anything else (e.g. if the guardrail heuristic ever stops flagging the fixed test prompt).

---

## 7. Testing / Verification

Locust files aren't pytest-collected (no `test_*.py` naming) and aren't run in CI — this is a manual benchmarking tool, not part of the automated suite. Verification for this sub-project is:
- The new migration applies cleanly (`alembic upgrade head`) and the seeded route is reachable via a real `mock-fast` chat request
- A short local Locust run (small user count, short duration) completes without errors and produces a report
- The safe-prompt pool is verified via `scan_prompt()` to never flag, one-time check during implementation

---

## 8. Out of Scope (this sub-project)

- Automating the outage/fallback comparison (manual two-run procedure only, per §2)
- Running Locust in CI (this is a manual benchmarking tool, not a CI gate)
- Distributed/multi-worker Locust (single-process is enough at this scale)
- The README case study itself (next sub-project — this one only produces the raw numbers)
