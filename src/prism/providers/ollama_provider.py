import httpx

from prism.config import settings
from prism.providers.base import BaseProvider, ChatResult


class OllamaProvider(BaseProvider):
    async def chat(
        self,
        messages: list[dict[str, str]],
        model: str,
        **kwargs: object,
    ) -> ChatResult:
        async with httpx.AsyncClient(timeout=settings.ollama_timeout_s) as client:
            response = await client.post(
                f"{settings.ollama_base_url}/v1/chat/completions",
                json={"model": model, "messages": messages, **kwargs},
            )
            response.raise_for_status()

        data: dict[str, object] = response.json()
        usage = data.get("usage") or {}
        assert isinstance(usage, dict)
        choices = data.get("choices") or []
        assert isinstance(choices, list)
        first_choice = choices[0]
        assert isinstance(first_choice, dict)
        message = first_choice.get("message") or {}
        assert isinstance(message, dict)

        return ChatResult(
            content=str(message.get("content", "")),
            prompt_tokens=int(usage.get("prompt_tokens", 0)),
            completion_tokens=int(usage.get("completion_tokens", 0)),
            raw=data,
        )
