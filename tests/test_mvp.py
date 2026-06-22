"""Tests for The Strategist MVP."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.pipeline import InferencePipeline
from src.router import RuleBasedRouter
from src.types import ModelTier


def test_router_simple_query():
    router = RuleBasedRouter()
    decision = router.route("今天天气怎么样？")
    assert decision.tier == ModelTier.SMALL
    assert decision.confidence > 0


def test_router_complex_query():
    router = RuleBasedRouter()
    query = "Prove that sqrt(2) is irrational and explain why by contradiction."
    decision = router.route(query)
    assert decision.tier in (ModelTier.MID, ModelTier.LARGE)
    assert decision.scores["keyword"] > 0


def test_pipeline_end_to_end():
    pipeline = InferencePipeline()
    result = pipeline.run("什么是机器学习？")
    assert result.response.content
    assert result.response.tier == result.routing.tier
    assert result.response.total_tokens > 0


def test_benchmark_report():
    from src.evaluation import build_report

    pipeline = InferencePipeline()
    results = [pipeline.run("Hello"), pipeline.run("Explain quantum computing in detail")]
    report = build_report(results)
    assert report.total_queries == 2
    assert "tier_distribution" in report.to_dict()


if __name__ == "__main__":
    test_router_simple_query()
    test_router_complex_query()
    test_pipeline_end_to_end()
    test_benchmark_report()
    print("All tests passed.")
