from prometheus_client import REGISTRY


def test_all_metrics_registered() -> None:
    from prism.observability import metrics  # noqa: F401

    # prometheus_client >= 0.12 strips _total from Counter family names in collect()
    names = {m.name for m in REGISTRY.collect()}
    assert "prism_requests" in names
    assert "prism_request_latency_seconds" in names
    assert "prism_cost_usd" in names
    assert "prism_cache_hits" in names
    assert "prism_cache_misses" in names
    assert "prism_guardrail_blocks" in names
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
        REGISTRY.get_sample_value("prism_circuit_breaker_open", {"provider": "ollama"})
        == 1.0
    )
    circuit_breaker_open.labels(provider="ollama").set(0.0)
    assert (
        REGISTRY.get_sample_value("prism_circuit_breaker_open", {"provider": "ollama"})
        == 0.0
    )
