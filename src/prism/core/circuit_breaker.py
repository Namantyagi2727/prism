import time
from dataclasses import dataclass

FAILURE_THRESHOLD = 3
OPEN_DURATION_S = 30


@dataclass
class _State:
    failures: int = 0
    opened_at: float | None = None


class CircuitBreaker:
    def __init__(
        self,
        failure_threshold: int = FAILURE_THRESHOLD,
        open_duration_s: float = OPEN_DURATION_S,
    ) -> None:
        self._threshold = failure_threshold
        self._duration = open_duration_s
        self._states: dict[str, _State] = {}

    def _state(self, provider: str) -> _State:
        if provider not in self._states:
            self._states[provider] = _State()
        return self._states[provider]

    def is_open(self, provider: str) -> bool:
        s = self._state(provider)
        if s.opened_at is None:
            return False
        if time.time() - s.opened_at >= self._duration:
            s.opened_at = None
            return False
        return True

    def record_failure(self, provider: str) -> None:
        s = self._state(provider)
        s.failures += 1
        if s.failures >= self._threshold:
            s.opened_at = time.time()

    def record_success(self, provider: str) -> None:
        self._states[provider] = _State()


circuit_breaker = CircuitBreaker()
