from decimal import Decimal

from prism.core.cost import calculate_cost


def test_ollama_is_free() -> None:
    cost = calculate_cost(
        "ollama", "llama3.2:3b", prompt_tokens=100, completion_tokens=50
    )
    assert cost == Decimal("0")


def test_openai_gpt4o_mini_cost() -> None:
    # $0.15 per million input, $0.60 per million output
    cost = calculate_cost(
        "openai", "gpt-4o-mini", prompt_tokens=1_000_000, completion_tokens=1_000_000
    )
    assert cost == Decimal("0.75")  # 0.15 + 0.60


def test_unknown_provider_returns_zero() -> None:
    cost = calculate_cost(
        "unknown", "mystery-model", prompt_tokens=500, completion_tokens=200
    )
    assert cost == Decimal("0")


def test_cost_scales_with_tokens() -> None:
    cost_small = calculate_cost(
        "openai", "gpt-4o-mini", prompt_tokens=100, completion_tokens=50
    )
    cost_large = calculate_cost(
        "openai", "gpt-4o-mini", prompt_tokens=1000, completion_tokens=500
    )
    assert cost_large > cost_small
    assert cost_large == cost_small * 10
