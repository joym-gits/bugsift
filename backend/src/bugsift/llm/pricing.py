"""Per-provider per-model pricing used to attribute cost to LLM calls.

Prices are ballpark public list prices in USD per 1M tokens at the time this
file was written; update as vendors change them. Unknown models return
``0.0`` — we'd rather under-report than crash.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelPricing:
    input_per_million: float
    output_per_million: float


PRICING: dict[str, dict[str, ModelPricing]] = {
    "anthropic": {
        "claude-opus-4-7": ModelPricing(15.00, 75.00),
        "claude-sonnet-4-6": ModelPricing(3.00, 15.00),
        "claude-haiku-4-5-20251001": ModelPricing(1.00, 5.00),
    },
    "openai": {
        "gpt-4o": ModelPricing(2.50, 10.00),
        "gpt-4o-mini": ModelPricing(0.15, 0.60),
        "text-embedding-3-small": ModelPricing(0.02, 0.0),
        "text-embedding-3-large": ModelPricing(0.13, 0.0),
    },
    "google": {
        "gemini-1.5-flash": ModelPricing(0.075, 0.30),
        "gemini-1.5-pro": ModelPricing(1.25, 5.00),
        "text-embedding-004": ModelPricing(0.0, 0.0),
    },
    "ollama": {},  # local models are free to run
}


def compute_cost(provider: str, model: str, prompt_tokens: int, completion_tokens: int) -> float:
    p = PRICING.get(provider, {}).get(model)
    if p is None:
        return 0.0
    return (
        (prompt_tokens / 1_000_000) * p.input_per_million
        + (completion_tokens / 1_000_000) * p.output_per_million
    )
