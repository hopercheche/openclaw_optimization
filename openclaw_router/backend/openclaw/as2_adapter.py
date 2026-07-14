from __future__ import annotations

import os
from dataclasses import dataclass, field
from importlib import import_module
from importlib.metadata import PackageNotFoundError, version
from typing import Any


@dataclass(slots=True)
class ModelProviderConfig:
    provider: str | None
    api_key: str | None
    base_url: str | None
    model: str

    @property
    def ready(self) -> bool:
        return self.api_key is not None

    def safe_dict(self) -> dict[str, str | bool | None]:
        return {
            "provider": self.provider,
            "ready": self.ready,
            "base_url": self.base_url,
            "model": self.model,
        }


@dataclass(slots=True)
class AS2Status:
    available: bool
    package_version: str | None
    runtime: str
    note: str
    model_ready: bool = False
    model_provider: str | None = None
    model_base_url: str | None = None
    default_model: str | None = None
    primitives: dict[str, bool] = field(default_factory=dict)
    architecture: dict[str, bool] = field(default_factory=dict)
    event_types: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "package_version": self.package_version,
            "runtime": self.runtime,
            "note": self.note,
            "model_ready": self.model_ready,
            "model_provider": self.model_provider,
            "model_base_url": self.model_base_url,
            "default_model": self.default_model,
            "primitives": self.primitives,
            "architecture": self.architecture,
            "event_types": self.event_types,
        }


def resolve_model_provider_config() -> ModelProviderConfig:
    if os.getenv("DEEPSEEK_API_KEY"):
        return ModelProviderConfig(
            provider="deepseek",
            api_key=os.getenv("DEEPSEEK_API_KEY"),
            base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
            model=os.getenv("OPENCLAW_DEEPSEEK_MODEL", "deepseek-v4-flash"),
        )

    if os.getenv("OPENAI_API_KEY"):
        return ModelProviderConfig(
            provider="openai",
            api_key=os.getenv("OPENAI_API_KEY"),
            base_url=os.getenv("OPENAI_BASE_URL") or os.getenv("OPENCLAW_OPENAI_BASE_URL"),
            model=os.getenv("OPENCLAW_OPENAI_MODEL", "gpt-4.1-mini"),
        )

    if os.getenv("DASHSCOPE_API_KEY"):
        return ModelProviderConfig(
            provider="dashscope",
            api_key=os.getenv("DASHSCOPE_API_KEY"),
            base_url=os.getenv("DASHSCOPE_BASE_URL"),
            model=os.getenv("OPENCLAW_DASHSCOPE_MODEL", "qwen-plus"),
        )

    return ModelProviderConfig(
        provider=None,
        api_key=None,
        base_url=None,
        model=os.getenv("OPENCLAW_OPENAI_MODEL", "gpt-4.1-mini"),
    )


def detect_as2() -> AS2Status:
    try:
        agentscope = import_module("agentscope")
    except Exception as exc:  # pragma: no cover - depends on local install
        return AS2Status(
            available=False,
            package_version=None,
            runtime="local_audit_runtime",
            note=f"agentscope import unavailable: {exc.__class__.__name__}",
        )

    try:
        package_version = getattr(agentscope, "__version__", None) or version("agentscope")
    except PackageNotFoundError:  # pragma: no cover
        package_version = "unknown"

    primitives: dict[str, bool] = {}
    for key, import_path in {
        "Agent": "agentscope.agent",
        "UserMsg": "agentscope.message",
        "AssistantMsg": "agentscope.message",
        "EventType": "agentscope.event",
        "Toolkit": "agentscope.tool",
    }.items():
        try:
            module = import_module(import_path)
            getattr(module, key)
            primitives[key] = True
        except Exception:
            primitives[key] = False

    architecture: dict[str, bool] = {}
    for key, import_path in {
        "AgentState": "agentscope.state",
        "PermissionMode": "agentscope.permission",
        "PermissionContext": "agentscope.permission",
        "ReActConfig": "agentscope.agent",
        "FunctionTool": "agentscope.tool",
        "Read": "agentscope.tool",
        "Grep": "agentscope.tool",
        "Glob": "agentscope.tool",
        "create_app": "agentscope.app",
        "LocalWorkspaceManager": "agentscope.app.workspace_manager",
    }.items():
        try:
            module = import_module(import_path)
            getattr(module, key)
            architecture[key] = True
        except Exception:
            architecture[key] = False

    event_types: list[str] = []
    try:
        event_type = getattr(import_module("agentscope.event"), "EventType")
        event_types = [item.name for item in event_type]
    except Exception:
        event_types = []

    provider_config = resolve_model_provider_config()

    all_core_primitives = all(primitives.values())
    agent_runtime_ready = all_core_primitives and all(
        architecture.get(key, False)
        for key in [
            "AgentState",
            "PermissionMode",
            "PermissionContext",
            "ReActConfig",
            "FunctionTool",
        ]
    )
    return AS2Status(
        available=agent_runtime_ready,
        package_version=package_version,
        runtime=(
            "agentscope_2_full_agent_runtime"
            if agent_runtime_ready
            else "agentscope_partial_import"
        ),
        note=(
            "agentscope agent, toolkit, permission, message, and event "
            "primitives are importable; model-backed execution requires "
            "provider credentials"
        ),
        model_ready=provider_config.ready,
        model_provider=provider_config.provider,
        model_base_url=provider_config.base_url,
        default_model=provider_config.model,
        primitives=primitives,
        architecture=architecture,
        event_types=event_types,
    )


def map_permission_mode_to_as2(mode: str) -> Any:
    permission_mode = import_module("agentscope.permission").PermissionMode
    normalized = mode.upper()
    mapping = {
        "DEFAULT": permission_mode.DEFAULT,
        "EXPLORE": permission_mode.EXPLORE,
        "ACCEPT_EDITS": permission_mode.ACCEPT_EDITS,
        "BYPASS": permission_mode.BYPASS,
        "DONT_ASK": permission_mode.DONT_ASK,
    }
    return mapping.get(normalized, permission_mode.DEFAULT)


LOCAL_TO_AS2_EVENT = {
    "run_started": "REPLY_START",
    "as2_model_started": "MODEL_CALL_START",
    "as2_model_result": "MODEL_CALL_END",
    "as2_model_skipped": "CUSTOM",
    "as2_model_fallback": "CUSTOM",
    "goal_analysis": "HINT_BLOCK",
    "candidate_step": "CUSTOM",
    "planning": "THINKING_BLOCK_DELTA",
    "reasoning": "THINKING_BLOCK_DELTA",
    "tool_call": "TOOL_CALL_START",
    "tool_result": "TOOL_RESULT_END",
    "critique": "CUSTOM",
    "human_gate": "REQUIRE_USER_CONFIRM",
    "final": "TEXT_BLOCK_END",
    "run_completed": "REPLY_END",
    "run_failed": "EXCEED_MAX_ITERS",
}


def map_local_event_to_as2(event_type: str, payload: dict[str, Any] | None = None) -> str:
    payload = payload or {}
    if event_type == "permission":
        behavior = payload.get("decision", {}).get("behavior")
        if behavior == "ask":
            return "REQUIRE_USER_CONFIRM"
        if behavior == "deny":
            return "TOOL_RESULT_END"
        return "CUSTOM"
    return LOCAL_TO_AS2_EVENT.get(event_type, "CUSTOM")


def build_user_message_snapshot(goal: str, run_id: str) -> dict[str, Any]:
    """Create a real AgentScope UserMsg and return audit-safe metadata."""

    try:
        user_msg_factory = getattr(import_module("agentscope.message"), "UserMsg")
        msg = user_msg_factory(
            name="user",
            content=goal,
            metadata={"run_id": run_id, "source": "openclaw_mvp"},
        )
        return {
            "available": True,
            "id": msg.id,
            "role": msg.role,
            "name": msg.name,
            "text": msg.get_text_content(),
            "content_block_types": [getattr(block, "type", type(block).__name__) for block in msg.content],
            "metadata": msg.metadata,
        }
    except Exception as exc:
        return {
            "available": False,
            "error": repr(exc),
        }
