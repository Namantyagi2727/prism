import pytest

from prism.providers.anthropic_provider import AnthropicProvider
from prism.providers.openai_provider import OpenAIProvider


@pytest.mark.asyncio
async def test_openai_provider_returns_chat_result() -> None:
    provider = OpenAIProvider()
    result = await provider.chat(
        messages=[{"role": "user", "content": "hi"}],
        model="gpt-4o-mini",
    )
    assert result.content == "[mock openai response]"
    assert result.prompt_tokens == 10
    assert result.completion_tokens == 5
    assert "choices" in result.raw


@pytest.mark.asyncio
async def test_anthropic_provider_returns_chat_result() -> None:
    provider = AnthropicProvider()
    result = await provider.chat(
        messages=[{"role": "user", "content": "hi"}],
        model="claude-haiku-4-5-20251001",
    )
    assert result.content == "[mock anthropic response]"
    assert result.prompt_tokens == 10
    assert result.completion_tokens == 5
    assert "choices" in result.raw
