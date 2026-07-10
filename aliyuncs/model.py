"""Chat model definition for the AliyunCS AgentScope provider."""

from __future__ import annotations

import os
from typing import Any, Literal

from agentscope.formatter import FormatterBase
from agentscope.model import OpenAIChatModel

from .credential import AliyunCSCredential, create_credential

ALIYUNCS_MODEL_ENV = "ALIYUNCS_MODEL"
ALIYUNCS_CHAT_MODEL_TYPE = "aliyuncs_chat"
DEFAULT_ALIYUNCS_MODEL = "deepseek-v3.2"


def get_model_name() -> str:
    """Read the default model name from the environment or local config."""

    return os.getenv(ALIYUNCS_MODEL_ENV, DEFAULT_ALIYUNCS_MODEL)


class AliyunCSChatModel(OpenAIChatModel):
    """AgentScope chat model for AliyunCS OpenAI-compatible MaaS API."""

    type: Literal["aliyuncs_chat"] = ALIYUNCS_CHAT_MODEL_TYPE
    """The chat model discriminator used by AgentScope."""

    def __init__(
        self,
        credential: AliyunCSCredential | None = None,
        model: str | None = None,
        parameters: OpenAIChatModel.Parameters | None = None,
        stream: bool = True,
        max_retries: int = 3,
        retry_delay: float = 1.0,
        context_size: int = 131072,
        formatter: FormatterBase | None = None,
        client_kwargs: dict[str, Any] | None = None,
        extra_body: dict[str, Any] | None = None,
    ) -> None:
        """Initialize the AliyunCS chat model with normalized defaults."""

        super().__init__(
            credential=credential or create_credential(),
            model=model or get_model_name(),
            parameters=parameters,
            stream=stream,
            max_retries=max_retries,
            retry_delay=retry_delay,
            context_size=context_size,
            formatter=formatter,
            client_kwargs=client_kwargs,
            extra_body=extra_body,
        )


def create_chat_model(
    *,
    credential: AliyunCSCredential | None = None,
    model: str | None = None,
    parameters: OpenAIChatModel.Parameters | None = None,
    stream: bool = True,
    max_retries: int = 3,
    retry_delay: float = 1.0,
    context_size: int = 131072,
    formatter: FormatterBase | None = None,
    client_kwargs: dict[str, Any] | None = None,
    extra_body: dict[str, Any] | None = None,
) -> AliyunCSChatModel:
    """Create a normalized AliyunCS chat model instance."""

    return AliyunCSChatModel(
        credential=credential,
        model=model,
        parameters=parameters,
        stream=stream,
        max_retries=max_retries,
        retry_delay=retry_delay,
        context_size=context_size,
        formatter=formatter,
        client_kwargs=client_kwargs,
        extra_body=extra_body,
    )