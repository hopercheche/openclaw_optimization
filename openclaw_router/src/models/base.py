from abc import ABC, abstractmethod

from src.types import LLMResponse, ModelTier


class BaseLLMProvider(ABC):
    @abstractmethod
    async def complete(self, prompt: str, tier: ModelTier) -> LLMResponse:
        """Generate a completion for the given prompt using the specified tier."""

    @abstractmethod
    def complete_sync(self, prompt: str, tier: ModelTier) -> LLMResponse:
        """Synchronous completion."""
