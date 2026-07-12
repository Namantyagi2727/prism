from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class ChatResult:
    content: str
    prompt_tokens: int
    completion_tokens: int
    raw: dict[str, object]


class BaseProvider(ABC):
    @abstractmethod
    async def chat(
        self,
        messages: list[dict[str, str]],
        model: str,
        **kwargs: object,
    ) -> ChatResult: ...
