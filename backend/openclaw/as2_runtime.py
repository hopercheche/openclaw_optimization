from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .as2_adapter import (
    ModelProviderConfig,
    map_permission_mode_to_as2,
    resolve_model_provider_config,
)
from .models import CandidateStep
from .permissions import PermissionEngine


ALLOWED_TOOLS = {
    "goal_analyzer",
    "workspace_inspector",
    "planner",
    "risk_model",
    "verifier",
    "audit_reader",
    "file_writer",
    "command_runner",
    "deploy_runner",
}

OPENCLAW_TOOL_NAMES = {
    "openclaw_audit_schema",
    "openclaw_workspace_inventory",
    "openclaw_permission_probe",
    "openclaw_score_candidate",
}


@dataclass(slots=True)
class AS2ModelEvent:
    event_type: str
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AS2PlanResult:
    used_model: bool
    model_name: str
    text: str = ""
    candidates: list[CandidateStep] = field(default_factory=list)
    raw_events: list[AS2ModelEvent] = field(default_factory=list)
    error: str | None = None
    architecture: dict[str, Any] = field(default_factory=dict)


def describe_as2_architecture(
    workspace_path: str | None = None,
    permission_mode: str = "DEFAULT",
) -> dict[str, Any]:
    """Return audit-safe metadata for the AS2 runtime this project wires up."""

    imports: dict[str, bool] = {}
    for name, import_path in {
        "Agent": "agentscope.agent",
        "ReActConfig": "agentscope.agent",
        "AgentState": "agentscope.state",
        "UserMsg": "agentscope.message",
        "OpenAIChatModel": "agentscope.model",
        "OpenAICredential": "agentscope.credential",
        "Toolkit": "agentscope.tool",
        "FunctionTool": "agentscope.tool",
        "PermissionMode": "agentscope.permission",
        "PermissionContext": "agentscope.permission",
        "EventType": "agentscope.event",
    }.items():
        try:
            module = __import__(import_path, fromlist=[name])
            getattr(module, name)
            imports[name] = True
        except Exception:
            imports[name] = False

    app_imports: dict[str, bool] = {}
    for name, import_path in {
        "create_app": "agentscope.app",
        "RedisStorage": "agentscope.app.storage",
        "RedisMessageBus": "agentscope.app.message_bus",
        "LocalWorkspaceManager": "agentscope.app.workspace_manager",
    }.items():
        try:
            module = __import__(import_path, fromlist=[name])
            getattr(module, name)
            app_imports[name] = True
        except Exception:
            app_imports[name] = False

    toolkit_ready = False
    tool_names: list[str] = []
    try:
        toolkit = build_openclaw_as2_toolkit(workspace_path, permission_mode)
        tool_names = _toolkit_tool_names(toolkit)
        toolkit_ready = OPENCLAW_TOOL_NAMES.issubset(set(tool_names))
    except Exception:
        toolkit_ready = False

    return {
        "runtime": "agentscope_2_full_agent_runtime",
        "agent_runtime_ready": all(imports.values()) and toolkit_ready,
        "app_server_ready": all(app_imports.values()),
        "app_server_note": (
            "AgentScope app server imports require optional FastAPI, Redis, and "
            "scheduler dependencies; OpenClaw runs a stdlib REST/SSE service "
            "and embeds the full Agent/Toolkit runtime directly."
        ),
        "imports": imports,
        "app_imports": app_imports,
        "toolkit_ready": toolkit_ready,
        "tool_names": tool_names,
        "permission_mode": permission_mode,
        "workspace_path": str(Path(workspace_path).resolve()) if workspace_path else None,
    }


def build_openclaw_as2_toolkit(
    workspace_path: str | None = None,
    permission_mode: str = "DEFAULT",
) -> Any:
    from agentscope.permission import PermissionBehavior, PermissionDecision
    from agentscope.tool import FunctionTool, Toolkit

    class OpenClawAuditFunctionTool(FunctionTool):
        async def check_permissions(
            self,
            *_args: Any,
            **_kwargs: Any,
        ) -> PermissionDecision:
            return PermissionDecision(
                behavior=PermissionBehavior.ALLOW,
                message="OpenClaw AS2 audit toolkit tools are read-only.",
            )

    workspace = Path(workspace_path or os.getcwd()).expanduser().resolve()
    permission_engine = PermissionEngine()

    def openclaw_audit_schema() -> dict[str, Any]:
        """Return the JSON schema required for OpenClaw planner candidates."""

        return {
            "required_top_level": ["candidates"],
            "allowed_tool_names": sorted(ALLOWED_TOOLS),
            "candidate_fields": [
                "title",
                "action",
                "tool_name",
                "rationale",
                "impact",
                "evidence_value",
                "reversibility",
                "risk",
                "mutates_workspace",
            ],
            "score_formula": "impact * 2 + evidence_value + reversibility - risk",
        }

    def openclaw_workspace_inventory(path: str = ".") -> dict[str, Any]:
        """List a workspace path without reading file contents or mutating files."""

        target = _resolve_inside_workspace(workspace, path)
        if target is None:
            return {
                "ok": False,
                "error": "path_outside_workspace",
                "workspace": str(workspace),
            }
        if not target.exists():
            return {
                "ok": False,
                "error": "path_not_found",
                "path": str(target),
            }
        if target.is_file():
            return {
                "ok": True,
                "path": str(target),
                "kind": "file",
                "size_bytes": target.stat().st_size,
            }
        entries = []
        for child in sorted(target.iterdir(), key=lambda item: item.name.lower())[:40]:
            if child.name.startswith("."):
                continue
            entries.append({
                "name": child.name,
                "kind": "dir" if child.is_dir() else "file",
            })
        return {
            "ok": True,
            "path": str(target),
            "kind": "dir",
            "entries": entries,
        }

    def openclaw_permission_probe(
        tool_name: str,
        action: str,
        mutates_workspace: bool = False,
    ) -> dict[str, Any]:
        """Classify a proposed action with OpenClaw's audit permission policy."""

        step = CandidateStep(
            title="AS2 permission probe",
            action=action,
            tool_name=tool_name if tool_name in ALLOWED_TOOLS else "planner",
            rationale="AgentScope runtime requested a permission forecast.",
            impact=3,
            evidence_value=3,
            reversibility=3,
            risk=3,
            mutates_workspace=mutates_workspace,
        )
        decision = permission_engine.decide(step, permission_mode)
        return decision.to_dict()

    def openclaw_score_candidate(
        impact: int,
        evidence_value: int,
        reversibility: int,
        risk: int,
    ) -> dict[str, int]:
        """Score one planner candidate using OpenClaw's bounded ranking rule."""

        bounded = {
            "impact": _bounded_int(impact, 3),
            "evidence_value": _bounded_int(evidence_value, 3),
            "reversibility": _bounded_int(reversibility, 3),
            "risk": _bounded_int(risk, 3),
        }
        bounded["score"] = (
            bounded["impact"] * 2
            + bounded["evidence_value"]
            + bounded["reversibility"]
            - bounded["risk"]
        )
        return bounded

    return Toolkit(
        tools=[
            OpenClawAuditFunctionTool(
                openclaw_audit_schema,
                is_read_only=True,
                description="Return OpenClaw's required planner JSON schema.",
            ),
            OpenClawAuditFunctionTool(
                openclaw_workspace_inventory,
                is_read_only=True,
                description="Inspect the configured workspace boundary safely.",
            ),
            OpenClawAuditFunctionTool(
                openclaw_permission_probe,
                is_read_only=True,
                description="Forecast allow/ask/deny for a proposed planner action.",
            ),
            OpenClawAuditFunctionTool(
                openclaw_score_candidate,
                is_read_only=True,
                description="Score a planner candidate by audit impact and risk.",
            ),
        ],
    )


def build_as2_agent_state(
    run_id: str,
    permission_mode: str,
    workspace_path: str,
) -> Any:
    from agentscope.permission import AdditionalWorkingDirectory
    from agentscope.state import AgentState

    workspace = str(Path(workspace_path).expanduser().resolve())
    state = AgentState(session_id=run_id)
    state.permission_context.mode = map_permission_mode_to_as2(permission_mode)
    state.permission_context.working_directories[workspace] = AdditionalWorkingDirectory(
        path=workspace,
        source="openclaw_run",
    )
    return state


def generate_as2_openai_plan(
    goal: str,
    permission_mode: str,
    workspace_path: str | None = None,
    run_id: str | None = None,
) -> AS2PlanResult:
    provider_config = resolve_model_provider_config()
    timeout_seconds = float(os.getenv("OPENCLAW_MODEL_TIMEOUT_SECONDS", "45"))
    architecture = describe_as2_architecture(workspace_path, permission_mode)
    if not provider_config.api_key:
        return AS2PlanResult(
            used_model=False,
            model_name=provider_config.model,
            error="No OpenAI-compatible provider key is set",
            architecture=architecture,
        )

    try:
        return asyncio.run(
            asyncio.wait_for(
                _generate(
                    goal,
                    permission_mode,
                    provider_config,
                    timeout_seconds,
                    workspace_path,
                    run_id,
                    architecture,
                ),
                timeout=timeout_seconds + 5,
            ),
        )
    except TimeoutError:
        return AS2PlanResult(
            used_model=False,
            model_name=provider_config.model,
            error=f"AS2 planner call timed out after {timeout_seconds:.0f}s",
            architecture=architecture,
        )


async def _generate(
    goal: str,
    permission_mode: str,
    provider_config: ModelProviderConfig,
    timeout_seconds: float,
    workspace_path: str | None,
    run_id: str | None,
    architecture: dict[str, Any],
) -> AS2PlanResult:
    try:
        from agentscope.agent import Agent, ReActConfig
        from agentscope.credential import OpenAICredential
        from agentscope.message import UserMsg
        from agentscope.model import OpenAIChatModel
    except Exception as exc:
        return AS2PlanResult(
            used_model=False,
            model_name=provider_config.model,
            architecture=architecture,
            error=_sanitize_error(f"AgentScope OpenAI imports failed: {exc!r}"),
        )

    system_prompt = (
        "You are the planner inside a complete audit-first AgentScope 2 runtime. "
        "You have an AgentScope Toolkit with OpenClaw audit tools. Use those "
        "tools when they help inspect the workspace boundary, permission policy, "
        "or candidate scoring. Your final answer must be JSON only, no markdown, "
        "and must not include secrets. Generate safe, auditable planner "
        "candidate steps. Every candidate must use one of these tool_name values: "
        f"{', '.join(sorted(ALLOWED_TOOLS))}. Score each candidate using "
        "integers 1-5 for impact, evidence_value, reversibility, and risk. "
        "Use mutates_workspace=true only when the action would write files, run "
        "commands, deploy, or affect external state."
    )
    user_prompt = {
        "goal": goal,
        "permission_mode": permission_mode,
        "provider": provider_config.provider,
        "workspace_path": workspace_path,
        "required_schema": {
            "candidates": [
                {
                    "title": "short title",
                    "action": "observable action",
                    "tool_name": "allowed tool name",
                    "rationale": "why this helps auditability",
                    "impact": 1,
                    "evidence_value": 1,
                    "reversibility": 1,
                    "risk": 1,
                    "mutates_workspace": False,
                },
            ],
            "strategy_notes": ["brief notes"],
        },
    }

    raw_events: list[AS2ModelEvent] = []
    text_parts: list[str] = []
    try:
        workspace = workspace_path or os.getcwd()
        agent = Agent(
            name="OpenClawPlanner",
            system_prompt=system_prompt,
            model=OpenAIChatModel(
                credential=OpenAICredential(
                    api_key=provider_config.api_key,
                    base_url=provider_config.base_url,
                ),
                model=provider_config.model,
                parameters=OpenAIChatModel.Parameters(
                    max_tokens=2000,
                    thinking_enable=False,
                    reasoning_effort="none",
                    temperature=0,
                ),
                stream=True,
                client_kwargs={"timeout": timeout_seconds},
            ),
            toolkit=build_openclaw_as2_toolkit(workspace, permission_mode),
            state=build_as2_agent_state(
                run_id or "openclaw_as2_runtime",
                permission_mode,
                workspace,
            ),
            react_config=ReActConfig(
                max_iters=int(os.getenv("OPENCLAW_AS2_MAX_ITERS", "6")),
                stop_on_reject=True,
            ),
        )

        async for event in agent.reply_stream(
            UserMsg(name="user", content=json.dumps(user_prompt, ensure_ascii=False)),
        ):
            event_type = _event_type_name(event)
            payload = _event_payload(event)
            raw_events.append(AS2ModelEvent(event_type=event_type, payload=payload))
            if event_type == "TEXT_BLOCK_DELTA":
                delta = getattr(event, "delta", "")
                if delta:
                    text_parts.append(str(delta))
    except Exception as exc:
        return AS2PlanResult(
            used_model=False,
            model_name=provider_config.model,
            raw_events=raw_events,
            architecture=architecture,
            error=_sanitize_error(f"AS2 OpenAI planner call failed: {exc!r}"),
        )

    text = "".join(text_parts).strip()
    try:
        candidates = _parse_candidates(text)
    except Exception as exc:
        return AS2PlanResult(
            used_model=False,
            model_name=provider_config.model,
            text=text,
            raw_events=raw_events,
            architecture=architecture,
            error=_sanitize_error(f"AS2 planner JSON parse failed: {exc!r}"),
        )

    return AS2PlanResult(
        used_model=True,
        model_name=provider_config.model,
        text=text,
        candidates=candidates,
        raw_events=raw_events,
        architecture=architecture,
    )


def _toolkit_tool_names(toolkit: Any) -> list[str]:
    names: list[str] = []
    for group in getattr(toolkit, "tool_groups", []):
        for item in getattr(group, "tools", []):
            tool = getattr(item, "tool", item)
            name = getattr(tool, "name", None)
            if name:
                names.append(str(name))
    return sorted(set(names))


def _resolve_inside_workspace(workspace: Path, path: str) -> Path | None:
    target = Path(path).expanduser()
    if not target.is_absolute():
        target = workspace / target
    resolved = target.resolve()
    try:
        resolved.relative_to(workspace)
    except ValueError:
        return None
    return resolved


def _event_type_name(event: Any) -> str:
    event_type = getattr(event, "type", type(event).__name__)
    return getattr(event_type, "name", str(event_type))


def _event_payload(event: Any) -> dict[str, Any]:
    if hasattr(event, "model_dump"):
        payload = event.model_dump(mode="json")
    elif hasattr(event, "dict"):
        payload = event.dict()
    else:
        payload = {
            key: value
            for key, value in vars(event).items()
            if not key.startswith("_")
        }
    payload.pop("delta", None)
    payload.pop("data", None)
    return _sanitize_payload(_truncate_payload(payload))


def _truncate_payload(value: Any, limit: int = 800) -> Any:
    if isinstance(value, str):
        return value if len(value) <= limit else value[:limit] + "...[truncated]"
    if isinstance(value, list):
        return [_truncate_payload(item, limit) for item in value[:20]]
    if isinstance(value, dict):
        return {
            str(key): _truncate_payload(item, limit)
            for key, item in list(value.items())[:30]
        }
    return value


def _sanitize_payload(value: Any) -> Any:
    if isinstance(value, str):
        return _sanitize_error(value)
    if isinstance(value, list):
        return [_sanitize_payload(item) for item in value]
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            normalized = str(key).lower()
            if any(secret_key in normalized for secret_key in ["api_key", "authorization", "token", "credential"]):
                sanitized[str(key)] = "[redacted]"
            else:
                sanitized[str(key)] = _sanitize_payload(item)
        return sanitized
    return value


def _parse_candidates(text: str) -> list[CandidateStep]:
    payload = json.loads(_extract_json(text))
    candidates_payload = payload.get("candidates", [])
    if not isinstance(candidates_payload, list):
        raise ValueError("candidates must be a list")

    candidates: list[CandidateStep] = []
    for item in candidates_payload[:8]:
        if not isinstance(item, dict):
            continue
        tool_name = str(item.get("tool_name", "planner"))
        if tool_name not in ALLOWED_TOOLS:
            tool_name = "planner"
        candidates.append(
            CandidateStep(
                title=str(item.get("title", "Untitled AS2 planner step"))[:120],
                action=str(item.get("action", ""))[:500],
                tool_name=tool_name,
                rationale=str(item.get("rationale", ""))[:500],
                impact=_bounded_int(item.get("impact"), 3),
                evidence_value=_bounded_int(item.get("evidence_value"), 3),
                reversibility=_bounded_int(item.get("reversibility"), 3),
                risk=_bounded_int(item.get("risk"), 3),
                mutates_workspace=bool(item.get("mutates_workspace", False)),
            ),
        )

    if not candidates:
        raise ValueError("no usable candidates")
    return candidates


def _extract_json(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?", "", stripped, flags=re.IGNORECASE).strip()
        stripped = re.sub(r"```$", "", stripped).strip()
    if stripped.startswith("{"):
        return stripped
    match = re.search(r"\{.*\}", stripped, flags=re.DOTALL)
    if not match:
        raise ValueError("no JSON object found")
    return match.group(0)


def _bounded_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(1, min(5, parsed))


def _sanitize_error(message: str) -> str:
    sanitized = re.sub(
        r"Incorrect API key provided:.*?api-keys\.",
        "Incorrect API key provided: [redacted].",
        message,
        flags=re.DOTALL,
    )
    sanitized = re.sub(r"sk-[A-Za-z0-9_*.-]{8,}", "sk-[redacted]", sanitized)
    sanitized = re.sub(
        r"Incorrect API key provided: [^']+",
        "Incorrect API key provided: [redacted]",
        sanitized,
    )
    return sanitized
