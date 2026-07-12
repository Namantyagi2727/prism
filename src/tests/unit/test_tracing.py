from prism.observability.tracing import setup_tracing


def test_setup_tracing_noop_on_empty_endpoint() -> None:
    setup_tracing(endpoint="")


def test_setup_tracing_nonreachable_endpoint_does_not_raise() -> None:
    # OTel exporters don't open a connection at setup time — errors appear on flush
    setup_tracing(endpoint="http://localhost:9999", service_name="prism-test")
