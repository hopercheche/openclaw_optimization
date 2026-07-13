from abc import ABC, abstractmethod

from src.types import ModelTier, RoutingDecision


class BaseRouter(ABC):
    @abstractmethod
    def route(self, query: str) -> RoutingDecision:
        """Decide which model tier to use for the given query."""
