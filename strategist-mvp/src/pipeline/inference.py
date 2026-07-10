from __future__ import annotations

from dataclasses import dataclass, field

from src.models import create_provider
from src.models.base import BaseLLMProvider
from src.router import RuleBasedRouter
from src.router.base import BaseRouter
from src.types import LLMResponse, RoutingDecision


@dataclass
class InferenceResult:
    query: str
    routing: RoutingDecision
    response: LLMResponse
    metadata: dict = field(default_factory=dict)


class InferencePipeline:
    """
    End-to-end pipeline: Input → Router → Model Call → Output
    """

    def __init__(
        self,
        router: BaseRouter | None = None,
        provider: BaseLLMProvider | None = None,
    ) -> None:
        self.router = router or RuleBasedRouter()
        self.provider = provider or create_provider()

    def run(self, query: str) -> InferenceResult:
        routing = self.router.route(query)
        response = self.provider.complete_sync(query, routing.tier)
        return InferenceResult(query=query, routing=routing, response=response)

    async def run_async(self, query: str) -> InferenceResult:
        routing = self.router.route(query)
        response = await self.provider.complete(query, routing.tier)
        return InferenceResult(query=query, routing=routing, response=response)
