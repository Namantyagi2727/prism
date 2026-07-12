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
