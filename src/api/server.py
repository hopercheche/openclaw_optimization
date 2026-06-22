"""FastAPI server for The Strategist MVP."""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI
from pydantic import BaseModel, Field

from src.config import get_provider_mode
from src.evaluation import build_report
from src.pipeline import InferencePipeline

app = FastAPI(
    title="The Strategist MVP",
    description="Rule-based LLM Routing API for OpenClaw Capstone",
    version="0.1.0",
)

pipeline = InferencePipeline()


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
    version: str


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    from src import __version__
    return HealthResponse(status="ok", provider=get_provider_mode(), version=__version__)


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


@app.post("/benchmark")
def benchmark(queries: list[str]) -> dict:
    results = [pipeline.run(q) for q in queries]
    return build_report(results).to_dict()
