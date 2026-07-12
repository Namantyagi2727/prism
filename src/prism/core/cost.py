from decimal import Decimal

# Rates per million tokens (input, output) in USD
_PRICING: dict[tuple[str, str], tuple[float, float]] = {
    ("ollama", "*"): (0.0, 0.0),
    ("openai", "gpt-4o-mini"): (0.15, 0.60),
    ("anthropic", "claude-haiku-4-5-20251001"): (0.25, 1.25),
}


def calculate_cost(
    provider: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
) -> Decimal:
    rates = (
        _PRICING.get((provider, model)) or _PRICING.get((provider, "*")) or (0.0, 0.0)
    )
    input_rate, output_rate = rates
    cost = (input_rate * prompt_tokens + output_rate * completion_tokens) / 1_000_000
    return Decimal(str(round(cost, 10)))
