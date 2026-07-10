"""Credential definition for the AliyunCS AgentScope provider.

The endpoint is OpenAI-compatible, so the credential intentionally mirrors the
fields used by :class:`agentscope.credential.OpenAICredential` while keeping an
independent discriminator type for AgentScope's credential registry.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Literal, Type

from agentscope.credential import OpenAICredential
from pydantic import ConfigDict, Field, SecretStr

if TYPE_CHECKING:
    from agentscope.model import ChatModelBase

ALIYUNCS_BASE_URL = (
    "https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
)
ALIYUNCS_API_KEY_ENV = "ALIYUNCS_API_KEY"
ALIYUNCS_CREDENTIAL_TYPE = "aliyuncs_credential"


def get_api_key() -> str:
    """Read the API key from the environment, falling back to local config."""

    return os.getenv(ALIYUNCS_API_KEY_ENV) or "sk-sp-D.RDYRR.RO0M.MEUCIQCp70g53dyHcsgHa83xxhhS1IUrsyErgVj138bPY1fr/QIgYWWZqgpECFIEfBQVsUtbbwP4PTZcXzS66FSgp2GnTu0="


class AliyunCSCredential(OpenAICredential):
    """Credential for AliyunCS OpenAI-compatible MaaS endpoint."""

    model_config = ConfigDict(title="AliyunCS MaaS API")

    type: Literal["aliyuncs_credential"] = ALIYUNCS_CREDENTIAL_TYPE
    """The credential discriminator used by AgentScope."""

    api_key: SecretStr = Field(
        default_factory=lambda: SecretStr(get_api_key()),
        title="API Key",
        description="The AliyunCS MaaS API key.",
    )

    organization: str | None = Field(
        default=None,
        title="Organization",
        description="Optional OpenAI-compatible organization id.",
    )

    base_url: str = Field(
        default=ALIYUNCS_BASE_URL,
        title="API Base URL",
        description="The AliyunCS OpenAI-compatible API endpoint.",
    )

    @classmethod
    def get_chat_model_class(cls) -> Type["ChatModelBase"]:
        """Return the chat model class consumed by this credential."""

        from .model import AliyunCSChatModel

        return AliyunCSChatModel


def create_credential(
    *,
    api_key: str | None = None,
    base_url: str = ALIYUNCS_BASE_URL,
    organization: str | None = None,
    name: str = "aliyuncs",
) -> AliyunCSCredential:
    """Create a normalized AliyunCS credential instance."""

    return AliyunCSCredential(
        name=name,
        api_key=api_key or get_api_key(),
        base_url=base_url,
        organization=organization,
    )