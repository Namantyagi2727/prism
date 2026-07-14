# Admin Analytics Dashboard — Design Spec

**Date:** 2026-07-14
**Status:** Approved
**Goal:** Phase 6, sub-project 1 of 4 (admin dashboard → Locust load test → architecture diagram → README case study). A single internal page that turns 24h of `request_log` data into something worth screenshotting for the portfolio README/demo, while doubling as a demonstration of hand-built (no-framework) frontend work.

---

## 1. What We're Building

One new route, `GET /admin/dashboard`, returning a server-rendered HTML page with four tab views (Overview, Cost & Teams, Performance, Safety) covering the trailing 24 hours of `request_log` data. All aggregation happens server-side in one request; the page embeds the results as JSON and uses vanilla JS (no framework, no build step) to switch tabs and render hand-rolled SVG charts.

This is explicitly scoped as an internal ops tool (it sits conceptually next to the existing Grafana dashboard), not a marketing page — visual restraint is a deliberate choice, not a shortcut.

---

## 2. Constraints & Decisions

| Topic | Decision |
|---|---|
| Rendering | Server-rendered HTML (Jinja2) — no Streamlit, no JSON-only API |
| Time range | Fixed last 24h, no query params |
| Auth | HTTP Basic (any username, `admin_secret` as password) — reuses the existing secret, works in a plain browser nav unlike the Bearer-token pattern the rest of `/admin/*` uses |
| Frontend stack | Vanilla JS + hand-rolled inline SVG charts, embedded JSON data island, no chart library, no build step |
| Scope signal | User explicitly asked this to also demonstrate frontend proficiency — multiple views, real charts, real interactivity, not a static table dump |
| Views | Overview / Cost & Teams / Performance / Safety — see §4 |

---

## 3. Visual Design

Token system (informed by `frontend-design` skill, deliberately dialed down from its marketing-page calibration — this is a dense internal tool, not a hero page):

- **Color:** background `#0B0E14`, panel surface `#11151C`, hairline border `#232838`, text primary `#E6E9EF`, text muted `#8890A0`, accent `#5B8DEF`, status red `#E5484D` (reserved — only appears when error rate / guardrail blocks are nonzero, so it stays meaningful)
- **Type:** system sans (Inter/system-ui) for labels/headers; monospace (ui-monospace/JetBrains Mono) for every number — stat tiles and table figures. Monospace numbers echo the terminal/observability tools already in this stack (Grafana/Prometheus/Jaeger) and keep columns of figures aligned.
- **Layout:** single page, no sidebar/nav chrome beyond the tab strip. Hairline dividers between sections instead of card shadows.
- **Signature move:** "terminal readout" feel — uppercase micro-labels over monospace figures, no boxes/shadows.
- **Interaction:** tab switch is a quiet fade/slide (respecting `prefers-reduced-motion`), chart points show a tooltip on hover, keyboard-focusable tab controls with visible focus rings.

Chart implementation follows the `dataviz` skill's palette/mark guidance when the views are actually built (not re-litigated here).

---

## 4. Views & Backend Queries

All four views are computed in one `GET /admin/dashboard` request against `request_log` joined to `api_keys`/`teams` where relevant, window = `created_at >= now() - interval '24 hours'`.

### Overview (default tab)
- Stat tiles: total requests, total cost (`sum(cost_usd)`), cache hit % (`cache_hit` true / total), error rate (`status_code >= 400` / total)
- Request volume: hourly buckets (`date_trunc('hour', created_at)`) → line/area chart
- Compact provider mix bar (count grouped by `provider_used`)

### Cost & Teams
- Cost by team: join `request_log → api_keys → teams`, group by team, `sum(cost_usd)`, `count(*)`
- Table: team name, request count, total cost, % of `teams.monthly_budget_usd` used (guard divide-by-zero if budget is 0)
- Estimated $ saved via cache: `count(cache_hit) * avg(cost_usd where cache_hit is false and same virtual_model)` — approximate, labeled as such in the UI

### Performance
- Latency percentiles (p50/p95/p99) via Postgres `percentile_cont` over `latency_ms`, overall and grouped by `provider_used`
- Fallback trigger rate over time (hourly buckets, `fallback_triggered` true / total)
- Provider mix with per-provider avg latency

### Safety
- Guardrail blocks over time (hourly buckets, rows where `provider_used = 'blocked'`)
- Blocks by reason: reuse the existing `_guardrail_label()` mapping from `chat.py` (pii_detected / prompt_injection / unknown) grouped from `guardrail_flag`
- Block rate: blocked / total attempted requests in window

---

## 5. Error Handling & Empty States

- No requests in the 24h window (fresh deploy, or run right after `docker-compose up`): tiles show `0`, charts render a quiet "no data yet" state — never a crash. `percentile_cont` on an empty set returns `NULL`; coalesce to `0` before serializing.
- No teams yet: Cost & Teams table renders an empty-state row, not an error.
- Basic Auth failure: `401` with `WWW-Authenticate: Basic` header so the browser actually shows its native prompt (this differs from the Bearer-only 401 the rest of `/admin/*` returns).
- `monthly_budget_usd == 0`: skip the percentage calculation for that team, show "no budget set" instead of dividing by zero.

---

## 6. Testing

Integration tests (testcontainers-backed, per Phase 5 infra) in `src/tests/integration/test_admin_dashboard.py`:
- Correct Basic Auth credentials → `200`, embedded JSON data reflects seeded `request_log` rows (including one guardrail-blocked row, to prove the Safety view has real data)
- Missing/wrong credentials → `401` with `WWW-Authenticate` header present
- Empty database (no requests) → `200`, all stats zeroed, no exception

No new unit-test surface beyond the aggregation-query logic, which is exercised through the integration test above (queries are the thing under test, not isolable pure functions).

---

## 7. Out of Scope (this sub-project)

- Configurable time ranges (deferred — fixed 24h only, per §2)
- Any write/mutation actions from the dashboard (view-only)
- Cross-team comparison charts beyond what's in Cost & Teams
- Streamlit or any second process/deployment target
