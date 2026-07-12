import pytest
from prism.core.circuit_breaker import CircuitBreaker
from prism.core.router import route
from prism.providers.base import BaseProvider, ChatResult


class _AlwaysFailProvider(BaseProvider):
    async def chat(
        self, messages: list[dict[str, str]], model: str, **kwargs: object
    ) -> ChatResult:
        raise RuntimeError("provider down")


class _SucceedProvider(BaseProvider):
    async def chat(
        self, messages: list[dict[str, str]], model: str, **kwargs: object
    ) -> ChatResult:
        return ChatResult(
            content="ok",
            prompt_tokens=5,
            completion_tokens=3,
            raw={"choices": [{"message": {"content": "ok"}}]},
        )


@pytest.mark.asyncio
async def test_uses_first_provider_when_healthy() -> None:
    providers = {"succeed": _SucceedProvider()}
    routes = [("succeed", "model-a", 1)]
    result, provider, model, fallback = await route(
        routes,
        providers,
        [{"role": "user", "content": "hi"}],
        0.7,
        cb=CircuitBreaker(),
    )
    assert provider == "succeed"
    assert fallback is False


@pytest.mark.asyncio
async def test_falls_back_on_failure() -> None:
    providers: dict[str, BaseProvider] = {
        "fail": _AlwaysFailProvider(),
        "succeed": _SucceedProvider(),
    }
    routes = [("fail", "model-a", 1), ("succeed", "model-b", 2)]
    result, provider, model, fallback = await route(
        routes,
        providers,
        [{"role": "user", "content": "hi"}],
        0.7,
        cb=CircuitBreaker(),
    )
    assert provider == "succeed"
    assert fallback is True


@pytest.mark.asyncio
async def test_raises_503_when_all_fail() -> None:
    from fastapi import HTTPException

    providers: dict[str, BaseProvider] = {"fail": _AlwaysFailProvider()}
    routes = [("fail", "model-a", 1)]
    with pytest.raises(HTTPException) as exc_info:
        await route(
            routes,
            providers,
            [{"role": "user", "content": "hi"}],
            0.7,
            cb=CircuitBreaker(),
        )
    assert exc_info.value.status_code == 503


@pytest.mark.asyncio
async def test_skips_open_circuit() -> None:
    cb = CircuitBreaker()
    for _ in range(3):
        cb.record_failure("fail")

    providers: dict[str, BaseProvider] = {
        "fail": _AlwaysFailProvider(),
        "succeed": _SucceedProvider(),
    }
    routes = [("fail", "model-a", 1), ("succeed", "model-b", 2)]
    result, provider, model, fallback = await route(
        routes,
        providers,
        [{"role": "user", "content": "hi"}],
        0.7,
        cb=cb,
    )
    assert provider == "succeed"
    assert fallback is True
