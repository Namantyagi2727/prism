from fastapi import HTTPException

from prism.core.circuit_breaker import CircuitBreaker, circuit_breaker
from prism.observability.metrics import circuit_breaker_open
from prism.providers.anthropic_provider import AnthropicProvider
from prism.providers.base import BaseProvider, ChatResult
from prism.providers.ollama_provider import OllamaProvider
from prism.providers.openai_provider import OpenAIProvider

PROVIDERS: dict[str, BaseProvider] = {
    "ollama": OllamaProvider(),
    "openai": OpenAIProvider(),
    "anthropic": AnthropicProvider(),
}


async def route(
    routes: list[tuple[str, str, int]],
    providers: dict[str, BaseProvider],
    messages: list[dict[str, str]],
    temperature: float,
    cb: CircuitBreaker = circuit_breaker,
) -> tuple[ChatResult, str, str, bool]:
    """Try each (provider, model) in priority order, return first success.

    routes: list of (provider_name, real_model, priority) sorted by priority
    Returns: (result, provider_name, real_model, fallback_triggered)
    Raises HTTPException(503) if all providers fail or are circuit-broken.
    """
    fallback_triggered = False
    last_error: Exception | None = None

    for provider_name, real_model, _ in routes:
        is_open = cb.is_open(provider_name)
        circuit_breaker_open.labels(provider=provider_name).set(1.0 if is_open else 0.0)
        if is_open:
            fallback_triggered = True
            continue

        provider = providers.get(provider_name)
        if provider is None:
            fallback_triggered = True
            continue

        try:
            result = await provider.chat(
                messages=messages,
                model=real_model,
                temperature=temperature,
            )
            cb.record_success(provider_name)
            circuit_breaker_open.labels(provider=provider_name).set(0.0)
            return result, provider_name, real_model, fallback_triggered
        except Exception as exc:
            cb.record_failure(provider_name)
            circuit_breaker_open.labels(provider=provider_name).set(
                1.0 if cb.is_open(provider_name) else 0.0
            )
            last_error = exc
            fallback_triggered = True

    raise HTTPException(
        status_code=503,
        detail=f"All providers failed. Last error: {last_error}",
    )
