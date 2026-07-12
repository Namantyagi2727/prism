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
    assert cb.is_open("ollama") is True  # 3rd failure opens it


def test_success_resets_failures() -> None:
    cb = CircuitBreaker()
    cb.record_failure("ollama")
    cb.record_failure("ollama")
    cb.record_success("ollama")
    cb.record_failure("ollama")
    cb.record_failure("ollama")
    assert cb.is_open("ollama") is False  # reset means we need 3 fresh failures


def test_half_open_after_cooldown() -> None:
    cb = CircuitBreaker(open_duration_s=0.05)
    cb.record_failure("ollama")
    cb.record_failure("ollama")
    cb.record_failure("ollama")
    assert cb.is_open("ollama") is True  # open within the 50ms window
    time.sleep(0.1)
    assert cb.is_open("ollama") is False  # cooldown expired → half-open


def test_independent_providers() -> None:
    cb = CircuitBreaker()
    cb.record_failure("ollama")
    cb.record_failure("ollama")
    cb.record_failure("ollama")
    assert cb.is_open("ollama") is True
    assert cb.is_open("openai") is False
