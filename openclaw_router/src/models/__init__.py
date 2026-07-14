from src.config import get_provider_mode
from src.models.base import BaseLLMProvider
from src.models.mock_provider import MockLLMProvider


def create_provider() -> BaseLLMProvider:
    mode = get_provider_mode()
    if mode == "openai":
        from src.models.openai_provider import OpenAIProvider

        return OpenAIProvider()
    return MockLLMProvider()
