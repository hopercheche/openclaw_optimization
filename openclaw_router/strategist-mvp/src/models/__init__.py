from src.config import get_provider_mode
from src.models.base import BaseLLMProvider
from src.models.mock_provider import MockLLMProvider
from src.models.openai_provider import OpenAIProvider


def create_provider() -> BaseLLMProvider:
    mode = get_provider_mode()
    if mode == "openai":
        return OpenAIProvider()
    return MockLLMProvider()
