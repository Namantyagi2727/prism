# Load Testing Prism

Locust load test for gateway-overhead, throughput, and fallback numbers
(feeds the README case study's benchmark table).

## Prerequisites

- `docker-compose up -d postgres redis app` (or run the app locally via uvicorn)
- `ollama serve` running with `llama3.2:3b` pulled (only needed for
  `RealInferenceUser` / combined runs — `GatewayOverheadUser` alone never
  touches Ollama)
- Migrations applied (`alembic upgrade head`), including the `mock-fast`
  virtual model seed

## Three ways to run it

**Gateway overhead only** (isolates Prism's own latency — auth, guardrail
scan, cache lookup/write, routing, logging — from any real inference time):

    uv run locust -f src/tests/load/locustfile.py GatewayOverheadUser \
      --host http://localhost:8000 --users 50 --spawn-rate 10 --run-time 2m \
      --headless --html src/tests/load/reports/overhead.html

**Realistic (real Ollama) only:**

    uv run locust -f src/tests/load/locustfile.py RealInferenceUser \
      --host http://localhost:8000 --users 5 --spawn-rate 1 --run-time 2m \
      --headless --html src/tests/load/reports/realistic.html

**Combined** (both scenarios together, ~9:1 ratio per their Locust
`weight` — this is the number to use for "throughput ceiling"):

    uv run locust -f src/tests/load/locustfile.py \
      --host http://localhost:8000 --users 50 --spawn-rate 10 --run-time 2m \
      --headless --html src/tests/load/reports/combined.html

## Outage / fallback comparison

The project guide wants an error-rate comparison with vs. without the
fallback chain enabled. This is a manual two-run procedure, not automated:

1. Run the **combined** scenario normally (see above) — record the error
   rate and RPS from the Locust report.
2. Stop `ollama serve` (or point `OLLAMA_BASE_URL` at an unreachable port
   and restart the app).
3. Re-run the **combined** scenario with the same parameters.
4. Compare the two reports' error rates. `RealInferenceUser` requests
   should now fall back to the mock providers instead of failing outright
   — check `/admin/dashboard`'s Performance tab (fallback rate) and
   Safety tab afterward to confirm the fallback chain is what kept the
   error rate low, not just that requests failed.

## After each run

Check `/admin/dashboard` (HTTP Basic Auth, any username, `admin_secret`
as the password) for cache-hit-rate and cost-by-team numbers — these
aren't Locust-native metrics but matter for the README's benchmark table
(cache hit rate %, estimated $ saved per 1,000 requests).
