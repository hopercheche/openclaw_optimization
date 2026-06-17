from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import dataclass, field
from typing import Any

from .as2_adapter import ModelProviderConfig, resolve_model_provider_config
from .models import CandidateStep


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


def generate_as2_openai_plan(goal: str, permission_mode: str) -> AS2PlanResult:
    provider_config = resolve_model_provider_config()
    timeout_seconds = float(os.getenv("OPENCLAW_MODEL_TIMEOUT_SECONDS", "45"))
    if not provider_config.api_key:
        return AS2PlanResult(
            used_model=False,
            model_name=provider_config.model,
            error="No OpenAI-compatible provider key is set",
        )

    try:
        return asyncio.run(
            asyncio.wait_for(
                _generate(goal, permission_mode, provider_config, timeout_seconds),
                timeout=timeout_seconds + 5,
            ),
        )
    except TimeoutError:
        return AS2PlanResult(
            used_model=False,
            model_name=provider_config.model,
            error=f"AS2 planner call timed out after {timeout_seconds:.0f}s",
        )


async def _generate(
    goal: str,
    permission_mode: str,
    provider_config: ModelProviderConfig,
    timeout_seconds: float,
) -> AS2PlanResult:
    try:
        from agentscope.agent import Agent
        from agentscope.credential import OpenAICredential
        from agentscope.message import UserMsg
        from agentscope.model import OpenAIChatModel
        from agentscope.tool import Toolkit
    except Exception as exc:
        return AS2PlanResult(
            used_model=False,
            model_name=provider_config.model,
            error=_sanitize_error(f"AgentScope OpenAI imports failed: {exc!r}"),
        )

    system_prompt = (
        "You are the planner inside an audit-first AgentScope 2 runtime. "
        "Return JSON only. No markdown. Do not include secrets. "
        "Generate safe, auditable planner candidate steps. "
        "Every candidate must use one of these tool_name values: "
        f"{', '.join(sorted(ALLOWED_TOOLS))}. "
        "Score each candidate using integers 1-5 for impact, evidence_value, "
        "reversibility, and risk. Use mutates_workspace=true only when the "
        "action would write files, run commands, deploy, or affect external state."
    )
    user_prompt = {
        "goal": goal,
            "permission_mode": permission_mode,
            "provider": provider_config.provider,
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
                }
            ],
            "strategy_notes": ["brief notes"],
        },
    }

    raw_events: list[AS2ModelEvent] = []
    text_parts: list[str] = []
    try:
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
            toolkit=Toolkit(tools=[]),
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
            error=_sanitize_error(f"AS2 planner JSON parse failed: {exc!r}"),
        )

    return AS2PlanResult(
        used_model=True,
        model_name=provider_config.model,
        text=text,
        candidates=candidates,
        raw_events=raw_events,
    )


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
    return _truncate_payload(payload)


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
            )
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
