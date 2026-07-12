from __future__ import annotations

import asyncio
import random
import time

from src.config import get_model_name, load_config
from src.models.base import BaseLLMProvider
from src.types import LLMResponse, ModelTier

_MOCK_RESPONSES = {
    ModelTier.SMALL: (
        "这是一个简洁的回答。基于快速推理，我认为问题的核心在于基本概念的理解。"
        "如需更深入分析，建议使用更大模型。"
    ),
    ModelTier.MID: (
        "经过中等复杂度的分析，我可以从多个角度回答您的问题。"
        "首先，问题的背景涉及几个关键因素；其次，需要权衡不同方案的利弊；"
        "最后，建议采取平衡的策略来处理。"
    ),
    ModelTier.LARGE: (
        "作为深度推理模型，我将为您提供全面的分析。"
        "第一步：识别问题的核心假设与约束条件。"
        "第二步：构建形式化论证框架，逐一验证各前提的有效性。"
        "第三步：综合多维度证据，给出经过严格推导的结论，并讨论可能的边界情况与反例。"
    ),
}


class MockLLMProvider(BaseLLMProvider):
    """Offline mock provider for demo and testing without API keys."""

    def __init__(self, latency_range_ms: tuple[int, int] = (200, 800)) -> None:
        self._latency_range = latency_range_ms
        self._config = load_config()

    def _estimate_tokens(self, text: str) -> int:
        return max(1, len(text) // 3)

    def _compute_cost(self, tier: ModelTier, prompt_tokens: int, completion_tokens: int) -> float:
        cfg = self._config["models"][tier.value]
        total = prompt_tokens + completion_tokens
        return (total / 1000) * cfg["cost_per_1k_tokens"]

    def complete_sync(self, prompt: str, tier: ModelTier) -> LLMResponse:
        time.sleep(random.randint(*self._latency_range) / 1000)
        prompt_tokens = self._estimate_tokens(prompt)
        content = _MOCK_RESPONSES[tier]
        completion_tokens = self._estimate_tokens(content)
        return LLMResponse(
            content=content,
            model=get_model_name(tier.value),
            tier=tier,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=random.randint(*self._latency_range),
            cost_usd=self._compute_cost(tier, prompt_tokens, completion_tokens),
        )

    async def complete(self, prompt: str, tier: ModelTier) -> LLMResponse:
        return await asyncio.to_thread(self.complete_sync, prompt, tier)
