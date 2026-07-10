"""Provider registration utilities for AgentScope.

Call :func:`register_provider` before creating the AgentScope application so
credentials stored with ``type='aliyuncs_credential'`` can be deserialized by
AgentScope's :class:`agentscope.credential.CredentialFactory`.
"""

from __future__ import annotations

from dataclasses import dataclass

from agentscope.credential import CredentialFactory

from .credential import (
    ALIYUNCS_BASE_URL,
    ALIYUNCS_CREDENTIAL_TYPE,
    AliyunCSCredential,
)
from .model import ALIYUNCS_CHAT_MODEL_TYPE, DEFAULT_ALIYUNCS_MODEL


@dataclass(frozen=True)
class ProviderConfig:
    """Metadata for the AliyunCS AgentScope provider."""

    name: str
    display_name: str
    base_url: str
    credential_type: str
    chat_model_type: str
    default_model: str


ALIYUNCS_PROVIDER = ProviderConfig(
    name="aliyuncs",
    display_name="AliyunCS MaaS",
    base_url=ALIYUNCS_BASE_URL,
    credential_type=ALIYUNCS_CREDENTIAL_TYPE,
    chat_model_type=ALIYUNCS_CHAT_MODEL_TYPE,
    default_model=DEFAULT_ALIYUNCS_MODEL,
)


def register_provider() -> ProviderConfig:
    """Register the AliyunCS credential type with AgentScope."""

    if CredentialFactory.get_credential_class(ALIYUNCS_CREDENTIAL_TYPE) is None:
        CredentialFactory.register_credential(AliyunCSCredential)
    return ALIYUNCS_PROVIDER