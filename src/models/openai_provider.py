from __future__ import annotations

import asyncio
import os
import time

from openai import OpenAI

from src.config import get_model_name, load_config
from src.models.base import BaseLLMProvider
from src.types import LLMResponse, ModelTier


class OpenAIProvider(BaseLLMProvider):
    """OpenAI-compatible API provider (OpenAI, OpenRouter, DashScope, etc.)."""

    def __init__(self) -> None:
        self._client = OpenAI(
            api_key=os.getenv("OPENAI_API_KEY"),
            base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        )
        self._config = load_config()

    def _compute_cost(self, tier: ModelTier, prompt_tokens: int, completion_tokens: int) -> float:
        cfg = self._config["models"][tier.value]
        total = prompt_tokens + completion_tokens
        return (total / 1000) * cfg["cost_per_1k_tokens"]

    def complete_sync(self, prompt: str, tier: ModelTier) -> LLMResponse:
        model = get_model_name(tier.value)
        start = time.perf_counter()
        response = self._client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
        )
        latency_ms = (time.perf_counter() - start) * 1000
        choice = response.choices[0]
        usage = response.usage
        prompt_tokens = usage.prompt_tokens if usage else 0
        completion_tokens = usage.completion_tokens if usage else 0
        return LLMResponse(
            content=choice.message.content or "",
            model=model,
            tier=tier,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=latency_ms,
            cost_usd=self._compute_cost(tier, prompt_tokens, completion_tokens),
            raw={"id": response.id},
        )

    async def complete(self, prompt: str, tier: ModelTier) -> LLMResponse:
        return await asyncio.to_thread(self.complete_sync, prompt, tier)
