from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ModelTier(str, Enum):
    SMALL = "small"
    MID = "mid"
    LARGE = "large"


@dataclass
class LLMResponse:
    content: str
    model: str
    tier: ModelTier
    prompt_tokens: int
    completion_tokens: int
    latency_ms: float
    cost_usd: float
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass
class RoutingDecision:
    tier: ModelTier
    confidence: float
    reasons: list[str]
    scores: dict[str, float]
