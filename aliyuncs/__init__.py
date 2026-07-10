"""AgentScope provider package for AliyunCS MaaS compatible API."""

from .credential import (
    ALIYUNCS_API_KEY_ENV,
    ALIYUNCS_BASE_URL,
    ALIYUNCS_CREDENTIAL_TYPE,
    AliyunCSCredential,
    create_credential,
    get_api_key,
)
from .model import (
    ALIYUNCS_CHAT_MODEL_TYPE,
    ALIYUNCS_MODEL_ENV,
    DEFAULT_ALIYUNCS_MODEL,
    AliyunCSChatModel,
    create_chat_model,
    get_model_name,
)
from .provider import ALIYUNCS_PROVIDER, ProviderConfig, register_provider

__all__ = [
    "ALIYUNCS_BASE_URL",
    "ALIYUNCS_CHAT_MODEL_TYPE",
    "ALIYUNCS_CREDENTIAL_TYPE",
    "ALIYUNCS_API_KEY_ENV",
    "ALIYUNCS_MODEL_ENV",
    "ALIYUNCS_PROVIDER",
    "DEFAULT_ALIYUNCS_API_KEY",
    "DEFAULT_ALIYUNCS_MODEL",
    "AliyunCSChatModel",
    "AliyunCSCredential",
    "ProviderConfig",
    "create_chat_model",
    "create_credential",
    "get_api_key",
    "get_model_name",
    "register_provider",
]