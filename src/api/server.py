"""FastAPI server for The Strategist MVP."""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI
from pydantic import BaseModel, Field

from src.config import get_provider_mode
from src.evaluation import build_report
from src.feature import FeatureExtractor
from src.pipeline import InferencePipeline

app = FastAPI(
    title="The Strategist MVP",
    description="Rule-based LLM Routing API for OpenClaw Capstone",
    version="0.2.0",
)

pipeline = InferencePipeline()
feature_extractor = FeatureExtractor()


class QueryRequest(BaseModel):
    query: str = Field(..., min_length=1, description="User query to route and answer")


class QueryResponse(BaseModel):
    query: str
    tier: str
    model: str
    confidence: float
    reasons: list[str]
    scores: dict[str, float]
    answer: str
    latency_ms: float
    total_tokens: int
    cost_usd: float


class HealthResponse(BaseModel):
    status: str
    provider: str
    embedding_backend: str
    version: str


class FeatureResponse(BaseModel):
    embedding: list[float]
    token_count: int
    char_count: int
    sentence_count: int
    reasoning_keyword_count: int
    embedding_backend: str


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    from src import __version__
    return HealthResponse(
        status="ok",
        provider=get_provider_mode(),
        embedding_backend=feature_extractor.embedding_backend,
        version=__version__,
    )


@app.post("/query", response_model=QueryResponse)
def query(req: QueryRequest) -> QueryResponse:
    result = pipeline.run(req.query)
    r, resp = result.routing, result.response
    return QueryResponse(
        query=req.query,
        tier=r.tier.value,
        model=resp.model,
        confidence=r.confidence,
        reasons=r.reasons,
        scores=r.scores,
        answer=resp.content,
        latency_ms=resp.latency_ms,
        total_tokens=resp.total_tokens,
        cost_usd=resp.cost_usd,
    )


@app.post("/route")
def route_only(req: QueryRequest) -> dict:
    """Return routing decision without calling the model."""
    decision = pipeline.router.route(req.query)
    return {
        "query": req.query,
        "tier": decision.tier.value,
        "confidence": decision.confidence,
        "reasons": decision.reasons,
        "scores": decision.scores,
    }


@app.post("/features", response_model=FeatureResponse)
def extract_features(req: QueryRequest) -> FeatureResponse:
    feature = feature_extractor.extract(req.query)
    return FeatureResponse(
        embedding=feature.embedding,
        token_count=feature.token_count,
        char_count=feature.char_count,
        sentence_count=feature.sentence_count,
        reasoning_keyword_count=feature.reasoning_keyword_count,
        embedding_backend=feature.metadata.get("backend", "unknown"),
    )


@app.post("/benchmark")
def benchmark(queries: list[str]) -> dict:
    results = [pipeline.run(q) for q in queries]
    return build_report(results).to_dict()
