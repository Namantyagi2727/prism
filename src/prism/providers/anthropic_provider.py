from prism.providers.base import BaseProvider, ChatResult


class AnthropicProvider(BaseProvider):
    async def chat(
        self,
        messages: list[dict[str, str]],
        model: str,
        **kwargs: object,
    ) -> ChatResult:
        return ChatResult(
            content="[mock anthropic response]",
            prompt_tokens=10,
            completion_tokens=5,
            raw={
                "id": "chatcmpl-mock-anthropic",
                "object": "chat.completion",
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": "[mock anthropic response]",
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "total_tokens": 15,
                },
            },
        )
