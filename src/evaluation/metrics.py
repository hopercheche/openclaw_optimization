from __future__ import annotations

from dataclasses import dataclass, field

from src.pipeline.inference import InferenceResult
from src.types import ModelTier


@dataclass
class QueryMetrics:
    query: str
    tier: ModelTier
    latency_ms: float
    total_tokens: int
    cost_usd: float
    confidence: float


@dataclass
class BenchmarkReport:
    results: list[QueryMetrics] = field(default_factory=list)

    @property
    def total_queries(self) -> int:
        return len(self.results)

    @property
    def avg_latency_ms(self) -> float:
        if not self.results:
            return 0.0
        return sum(r.latency_ms for r in self.results) / len(self.results)

    @property
    def avg_tokens(self) -> float:
        if not self.results:
            return 0.0
        return sum(r.total_tokens for r in self.results) / len(self.results)

    @property
    def total_cost_usd(self) -> float:
        return sum(r.cost_usd for r in self.results)

    @property
    def tier_distribution(self) -> dict[str, int]:
        dist: dict[str, int] = {"small": 0, "mid": 0, "large": 0}
        for r in self.results:
            dist[r.tier.value] += 1
        return dist

    def cost_vs_always_large(self) -> dict[str, float]:
        """Compare routed cost against always using large model."""
        if not self.results:
            return {"routed_cost": 0, "always_large_cost": 0, "savings_pct": 0}
        routed = self.total_cost_usd
        # Estimate: if all queries used large tier, scale by cost multiplier ratio
        always_large = sum(
            r.cost_usd * (20.0 / {ModelTier.SMALL: 1.0, ModelTier.MID: 5.0, ModelTier.LARGE: 20.0}[r.tier])
            for r in self.results
        )
        savings = ((always_large - routed) / always_large * 100) if always_large > 0 else 0
        return {
            "routed_cost": round(routed, 6),
            "always_large_cost": round(always_large, 6),
            "savings_pct": round(savings, 1),
        }

    def to_dict(self) -> dict:
        return {
            "total_queries": self.total_queries,
            "avg_latency_ms": round(self.avg_latency_ms, 1),
            "avg_tokens": round(self.avg_tokens, 1),
            "total_cost_usd": round(self.total_cost_usd, 6),
            "tier_distribution": self.tier_distribution,
            "cost_comparison": self.cost_vs_always_large(),
        }


def result_to_metrics(result: InferenceResult) -> QueryMetrics:
    return QueryMetrics(
        query=result.query,
        tier=result.routing.tier,
        latency_ms=result.response.latency_ms,
        total_tokens=result.response.total_tokens,
        cost_usd=result.response.cost_usd,
        confidence=result.routing.confidence,
    )


def build_report(results: list[InferenceResult]) -> BenchmarkReport:
    return BenchmarkReport(results=[result_to_metrics(r) for r in results])
