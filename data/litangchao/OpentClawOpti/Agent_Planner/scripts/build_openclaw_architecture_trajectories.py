#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


AGENT_PLANNER_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_TRANSITIONS = AGENT_PLANNER_ROOT / "rewards" / "openclaw_architecture_transitions.jsonl"
DEFAULT_OUTPUT_SFT = AGENT_PLANNER_ROOT / "processed" / "openclaw_architecture_sft.jsonl"
ASSISTANT_MARKER = "<|im_start|>assistant\n"
IM_END = "<|im_end|>"
MAX_TEXT_CHARS = 2400


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Export OpenClaw planner events into architecture-aware "
            "Agent-Lightning-style transitions and standalone SFT rows."
        ),
    )
    parser.add_argument(
        "--input-root",
        type=Path,
        action="append",
        default=[],
        help="Root to scan for runs/*/events.jsonl. May be provided multiple times.",
    )
    parser.add_argument("--output-transitions", type=Path, default=DEFAULT_OUTPUT_TRANSITIONS)
    parser.add_argument("--output-sft", type=Path, default=DEFAULT_OUTPUT_SFT)
    parser.add_argument(
        "--no-legacy",
        action="store_true",
        help="Only export runs that already contain task_queue_created/verifier_result events.",
    )
    parser.add_argument("--limit-runs", type=int, default=0)
    parser.add_argument("--limit-transitions", type=int, default=0)
    args = parser.parse_args()

    input_roots = args.input_root or [Path("data/benchmarks"), Path("data/runs")]
    stats = export_architecture_trajectories(
        input_roots=input_roots,
        output_transitions=args.output_transitions,
        output_sft=args.output_sft,
        include_legacy=not args.no_legacy,
        limit_runs=args.limit_runs,
        limit_transitions=args.limit_transitions,
    )
    print(json.dumps(stats, ensure_ascii=False, indent=2))


def export_architecture_trajectories(
    *,
    input_roots: list[Path],
    output_transitions: Path,
    output_sft: Path,
    include_legacy: bool = True,
    limit_runs: int = 0,
    limit_transitions: int = 0,
) -> dict[str, Any]:
    output_transitions.parent.mkdir(parents=True, exist_ok=True)
    output_sft.parent.mkdir(parents=True, exist_ok=True)
    event_paths = _find_event_paths(input_roots)

    stats: Counter[str] = Counter()
    reward_sum = 0.0
    model_tiers: Counter[str] = Counter()
    next_actions: Counter[str] = Counter()
    strategies: Counter[str] = Counter()
    source_modes: Counter[str] = Counter()

    with output_transitions.open("w", encoding="utf-8") as transition_handle, output_sft.open(
        "w",
        encoding="utf-8",
    ) as sft_handle:
        for events_path in event_paths:
            if limit_runs and stats["runs_scanned"] >= limit_runs:
                break
            stats["runs_scanned"] += 1
            events = _load_jsonl(events_path)
            if not events:
                stats["empty_runs"] += 1
                continue
            state = _load_json(events_path.with_name("state.json")) or {}
            run_rows = _run_to_rows(
                events_path=events_path,
                state=state,
                events=events,
                include_legacy=include_legacy,
            )
            if not run_rows:
                stats["runs_without_exportable_steps"] += 1
                continue
            stats["runs_exported"] += 1
            for transition, sft_row in run_rows:
                if limit_transitions and stats["transitions"] >= limit_transitions:
                    break
                transition_handle.write(json.dumps(transition, ensure_ascii=False) + "\n")
                sft_handle.write(json.dumps(sft_row, ensure_ascii=False) + "\n")
                stats["transitions"] += 1
                stats["sft_rows"] += 1
                reward_sum += float(transition.get("reward") or 0.0)
                action = transition.get("action") or {}
                action_payload = action.get("planner_action") or {}
                model_tiers[str(action_payload.get("model_tier") or "unknown")] += 1
                verifier = transition.get("verifier") or {}
                next_actions[str(verifier.get("next_action") or "unknown")] += 1
                source = transition.get("source") or {}
                source_modes["legacy" if source.get("legacy") else "architecture"] += 1
                strategy = str(transition.get("state", {}).get("planner_strategy") or "unknown")
                strategies[strategy] += 1
            if limit_transitions and stats["transitions"] >= limit_transitions:
                break

    stats_dict: dict[str, Any] = dict(stats)
    stats_dict.update({
        "input_roots": [str(path) for path in input_roots],
        "output_transitions": str(output_transitions),
        "output_sft": str(output_sft),
        "include_legacy": include_legacy,
        "reward_sum": round(reward_sum, 6),
        "mean_reward": round(reward_sum / stats["transitions"], 6) if stats["transitions"] else 0.0,
        "model_tiers": dict(sorted(model_tiers.items())),
        "next_actions": dict(sorted(next_actions.items())),
        "planner_strategies": dict(sorted(strategies.items())),
        "source_modes": dict(sorted(source_modes.items())),
    })
    summary_path = output_transitions.with_suffix(output_transitions.suffix + ".summary.json")
    summary_path.write_text(json.dumps(stats_dict, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return stats_dict


def _find_event_paths(input_roots: list[Path]) -> list[Path]:
    paths: list[Path] = []
    seen: set[Path] = set()
    for root in input_roots:
        if root.is_file() and root.name == "events.jsonl":
            candidates = [root]
        elif root.exists():
            candidates = sorted(root.rglob("events.jsonl"))
        else:
            candidates = []
        for path in candidates:
            resolved = path.resolve()
            if resolved not in seen:
                seen.add(resolved)
                paths.append(path)
    return sorted(paths)


def _run_to_rows(
    *,
    events_path: Path,
    state: dict[str, Any],
    events: list[dict[str, Any]],
    include_legacy: bool,
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    planning_event = _first_event(events, "planning")
    selected_tools = list((planning_event.get("data", {}).get("selected_tools") if planning_event else []) or [])
    queue_event = _first_event(events, "task_queue_created")
    task_queue = list((queue_event.get("data", {}).get("task_queue") if queue_event else []) or [])
    source_meta = _source_meta(events_path)
    queue_closed = _first_event(events, "planner_queue_closed")
    queue_next_action = str(queue_closed.get("data", {}).get("next_action") or "complete") if queue_closed else "complete"
    trajectory_reward = _trajectory_reward(queue_next_action, state)

    if task_queue:
        return _architecture_rows(
            events_path=events_path,
            state=state,
            events=events,
            task_queue=task_queue,
            selected_tools=selected_tools,
            source_meta=source_meta,
            trajectory_reward=trajectory_reward,
        )

    if not include_legacy:
        return []
    return _legacy_rows(
        events_path=events_path,
        state=state,
        events=events,
        selected_tools=selected_tools,
        source_meta=source_meta,
        trajectory_reward=trajectory_reward,
    )


def _architecture_rows(
    *,
    events_path: Path,
    state: dict[str, Any],
    events: list[dict[str, Any]],
    task_queue: list[dict[str, Any]],
    selected_tools: list[str],
    source_meta: dict[str, Any],
    trajectory_reward: float,
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    rows: list[tuple[dict[str, Any], dict[str, Any]]] = []
    episode_id = _episode_id(events_path, state, source_meta)
    previous_actions: list[dict[str, Any]] = []
    for timestep, subtask in enumerate(task_queue):
        subtask_id = str(subtask.get("task_id") or f"{episode_id}-subtask-{timestep + 1:02d}")
        permission = _first_event(events, "permission", subtask_id=subtask_id)
        tool_result = _first_event(events, "tool_result", subtask_id=subtask_id)
        verifier = _first_event(events, "verifier_result", subtask_id=subtask_id)
        next_action = str(verifier.get("data", {}).get("next_action") or "missing_verifier") if verifier else "missing_verifier"
        reward, reward_reason = _step_reward(subtask, permission, verifier)
        done = timestep == len(task_queue) - 1 or next_action in {"await_human", "replan", "complete"}
        transition = _transition_row(
            schema_mode="architecture",
            episode_id=episode_id,
            timestep=timestep,
            state=state,
            selected_tools=selected_tools,
            subtask=subtask,
            previous_actions=previous_actions,
            permission=permission,
            tool_result=tool_result,
            verifier=verifier,
            reward=reward,
            reward_reason=reward_reason,
            done=done,
            trajectory_reward=trajectory_reward,
            source_meta=source_meta,
        )
        sft_row = _sft_row(transition)
        rows.append((transition, sft_row))
        previous_actions.append(_history_action(subtask, next_action, reward))
    return rows


def _legacy_rows(
    *,
    events_path: Path,
    state: dict[str, Any],
    events: list[dict[str, Any]],
    selected_tools: list[str],
    source_meta: dict[str, Any],
    trajectory_reward: float,
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    rows: list[tuple[dict[str, Any], dict[str, Any]]] = []
    episode_id = _episode_id(events_path, state, source_meta)
    reasonings = [event for event in events if event.get("event_type") == "reasoning" and event.get("data", {}).get("step")]
    permissions = [event for event in events if event.get("event_type") == "permission"]
    previous_actions: list[dict[str, Any]] = []
    for timestep, reasoning in enumerate(reasonings):
        step = reasoning.get("data", {}).get("step") or {}
        subtask = _legacy_subtask(episode_id, timestep, step)
        permission = _match_legacy_permission(permissions, step, timestep)
        tool_result = _match_legacy_tool_result(events, step)
        verifier = _legacy_verifier(step, permission, tool_result)
        reward, reward_reason = _step_reward(subtask, permission, verifier)
        done = timestep == len(reasonings) - 1
        transition = _transition_row(
            schema_mode="legacy",
            episode_id=episode_id,
            timestep=timestep,
            state=state,
            selected_tools=selected_tools,
            subtask=subtask,
            previous_actions=previous_actions,
            permission=permission,
            tool_result=tool_result,
            verifier=verifier,
            reward=reward,
            reward_reason=reward_reason,
            done=done,
            trajectory_reward=trajectory_reward,
            source_meta={**source_meta, "legacy": True},
        )
        sft_row = _sft_row(transition)
        rows.append((transition, sft_row))
        previous_actions.append(_history_action(subtask, transition["verifier"]["next_action"], reward))
    return rows


def _transition_row(
    *,
    schema_mode: str,
    episode_id: str,
    timestep: int,
    state: dict[str, Any],
    selected_tools: list[str],
    subtask: dict[str, Any],
    previous_actions: list[dict[str, Any]],
    permission: dict[str, Any] | None,
    tool_result: dict[str, Any] | None,
    verifier: dict[str, Any] | None,
    reward: float,
    reward_reason: str,
    done: bool,
    trajectory_reward: float,
    source_meta: dict[str, Any],
) -> dict[str, Any]:
    action_payload = _planner_action(subtask, verifier)
    verifier_payload = _verifier_payload(verifier, permission, reward_reason)
    return {
        "schema": "agent_lightning_transition_v0",
        "domain_schema": "openclaw_architecture_transition_v0",
        "episode_id": episode_id,
        "transition_id": f"{episode_id}:{timestep:04d}",
        "timestep": timestep,
        "state": {
            "goal": _shorten(str(state.get("goal") or "")),
            "permission_mode": state.get("permission_mode"),
            "planner_strategy": state.get("planner_strategy"),
            "selected_tools": selected_tools,
            "history": {
                "previous_planner_actions": previous_actions[-4:],
            },
            "subtask_candidate": {
                "task_id": subtask.get("task_id"),
                "title": subtask.get("title"),
                "objective": subtask.get("objective"),
                "risk_level": subtask.get("risk_level"),
                "success_criteria": subtask.get("success_criteria") or [],
            },
        },
        "action": {
            "type": "planner_architecture_action",
            "content": json.dumps(action_payload, ensure_ascii=False, separators=(",", ":")),
            "planner_action": action_payload,
        },
        "reward": reward,
        "done": done,
        "trajectory_reward": trajectory_reward,
        "credit_assignment": "verifier_step",
        "verifier": verifier_payload,
        "evidence": {
            "permission": (permission or {}).get("data", {}).get("decision"),
            "tool_result": (tool_result or {}).get("data", {}).get("result"),
        },
        "source": {
            **source_meta,
            "schema_mode": schema_mode,
        },
    }


def _planner_action(subtask: dict[str, Any], verifier: dict[str, Any] | None) -> dict[str, Any]:
    verifier_data = (verifier or {}).get("data", {})
    return {
        "task_id": subtask.get("task_id"),
        "tool_name": subtask.get("tool_name"),
        "action": subtask.get("action"),
        "model_tier": subtask.get("model_tier") or "unknown",
        "risk_level": subtask.get("risk_level") or "unknown",
        "context_policy": subtask.get("context_policy") or "legacy_event_replay",
        "memory_queries": subtask.get("memory_queries") or [],
        "success_criteria": subtask.get("success_criteria") or [],
        "executor_kind": subtask.get("executor_kind") or "unknown",
        "expected_next_action": verifier_data.get("next_action") or "missing_verifier",
    }


def _verifier_payload(
    verifier: dict[str, Any] | None,
    permission: dict[str, Any] | None,
    reward_reason: str,
) -> dict[str, Any]:
    verifier_data = (verifier or {}).get("data", {})
    permission_data = (permission or {}).get("data", {}).get("decision") or {}
    outcome = verifier_data.get("outcome")
    if not outcome:
        behavior = permission_data.get("behavior")
        outcome = "completed" if behavior == "allow" else ("requires_human" if behavior == "ask" else "denied")
    return {
        "outcome": outcome,
        "decision_behavior": verifier_data.get("decision_behavior") or permission_data.get("behavior"),
        "next_action": verifier_data.get("next_action") or _fallback_next_action(permission_data),
        "evidence_complete": bool(verifier_data.get("evidence_complete", verifier is not None)),
        "residual_risk": verifier_data.get("residual_risk"),
        "critique": verifier_data.get("critique"),
        "reward_reason": reward_reason,
    }


def _sft_row(transition: dict[str, Any]) -> dict[str, Any]:
    state = transition["state"]
    action = transition["action"]["planner_action"]
    verifier = transition["verifier"]
    target = {
        "analysis": (
            f"Select {action['tool_name']} for subtask {action.get('task_id')}; "
            f"risk={action['risk_level']}, model={action['model_tier']}, "
            f"context={action['context_policy']}."
        ),
        "plan": (
            f"Strategist uses {action['model_tier']}; Architect uses {action['context_policy']}; "
            f"Executor kind is {action['executor_kind']}; Verifier next_action is {verifier['next_action']}."
        ),
        "commands": [
            {
                "keystrokes": (
                    "openclaw.plan_subtask "
                    f"--tool {_safe_arg(action['tool_name'])} "
                    f"--model-tier {_safe_arg(action['model_tier'])} "
                    f"--context-policy {_safe_arg(action['context_policy'])} "
                    f"--next-action {_safe_arg(verifier['next_action'])}"
                ),
                "duration": 1,
            }
        ],
        "task_complete": bool(transition["done"]),
        "architecture": action,
        "verifier": verifier,
        "reward": transition["reward"],
    }
    prompt = (
        "<|im_start|>system\n"
        "You are the OpenClaw Agent_Planner. Decide one architecture-aligned planner subtask. "
        "Return exactly one JSON object.\n"
        "<|im_end|>\n"
        "<|im_start|>user\n"
        f"Goal: {state['goal']}\n"
        f"Permission mode: {state.get('permission_mode')}\n"
        f"Planner strategy: {state.get('planner_strategy')}\n"
        f"Selected tools: {state.get('selected_tools')}\n"
        f"Previous planner actions: {state.get('history', {}).get('previous_planner_actions', [])}\n"
        f"Subtask candidate: {json.dumps(state.get('subtask_candidate'), ensure_ascii=False)}\n"
        "Choose model_tier, context_policy, executor kind, and verifier next_action.\n"
        "<|im_end|>\n"
        f"{ASSISTANT_MARKER}"
    )
    return {
        "source": "openclaw_architecture_events",
        "format": "openclaw_architecture_sft_text",
        "episode_id": transition["episode_id"],
        "transition_id": transition["transition_id"],
        "reward": transition["reward"],
        "text": f"{prompt}{json.dumps(target, ensure_ascii=False, separators=(',', ':'))}{IM_END}\n",
    }


def _step_reward(
    subtask: dict[str, Any],
    permission: dict[str, Any] | None,
    verifier: dict[str, Any] | None,
) -> tuple[float, str]:
    verifier_data = (verifier or {}).get("data", {})
    permission_data = (permission or {}).get("data", {}).get("decision") or {}
    outcome = str(verifier_data.get("outcome") or "")
    behavior = str(verifier_data.get("decision_behavior") or permission_data.get("behavior") or "")
    residual_risk = int(verifier_data.get("residual_risk") or 0)
    if outcome == "completed" or behavior == "allow":
        reward = max(0.6, 1.0 - min(residual_risk, 5) * 0.04)
        return round(reward, 4), "completed_with_verifier_evidence"
    if outcome == "requires_human" or behavior == "ask":
        return 0.45, "safe_human_gate"
    if outcome == "denied" or behavior == "deny":
        return 0.35, "safe_policy_block"
    if not verifier:
        return -0.25, "missing_verifier_result"
    risk_level = str(subtask.get("risk_level") or "unknown")
    return (0.1, f"unknown_outcome_risk_{risk_level}")


def _trajectory_reward(queue_next_action: str, state: dict[str, Any]) -> float:
    if queue_next_action == "complete" and state.get("status") in {None, "", "completed"}:
        return 1.0
    if queue_next_action == "await_human":
        return 0.55
    if queue_next_action == "replan":
        return 0.25
    return 0.5


def _history_action(subtask: dict[str, Any], next_action: str, reward: float) -> dict[str, Any]:
    return {
        "tool_name": subtask.get("tool_name"),
        "model_tier": subtask.get("model_tier") or "unknown",
        "context_policy": subtask.get("context_policy") or "legacy_event_replay",
        "next_action": next_action,
        "reward": reward,
    }


def _legacy_subtask(episode_id: str, timestep: int, step: dict[str, Any]) -> dict[str, Any]:
    tool_name = str(step.get("tool_name") or "unknown")
    risk = int(step.get("risk") or 0)
    if risk >= 5:
        risk_level = "high"
        model_tier = "large"
    elif risk >= 3 or bool(step.get("mutates_workspace")):
        risk_level = "medium"
        model_tier = "medium"
    else:
        risk_level = "low"
        model_tier = "small"
    return {
        "task_id": f"{episode_id}-legacy-{timestep + 1:02d}",
        "index": timestep + 1,
        "title": step.get("title"),
        "objective": step.get("rationale"),
        "tool_name": tool_name,
        "action": step.get("action"),
        "model_tier": model_tier,
        "risk_level": risk_level,
        "context_policy": "legacy_event_replay",
        "memory_queries": [f"tool:{tool_name}", "context:legacy_event_replay"],
        "success_criteria": [
            "permission decision is recorded before execution",
            "legacy event replay infers verifier outcome",
        ],
        "executor_kind": "legacy_tool",
    }


def _legacy_verifier(
    step: dict[str, Any],
    permission: dict[str, Any] | None,
    tool_result: dict[str, Any] | None,
) -> dict[str, Any]:
    decision = (permission or {}).get("data", {}).get("decision") or {}
    behavior = str(decision.get("behavior") or "")
    if behavior == "ask":
        outcome = "requires_human"
        next_action = "await_human"
    elif behavior == "deny":
        outcome = "denied"
        next_action = "replan"
    else:
        outcome = "completed" if tool_result else "unknown"
        next_action = "next_subtask" if tool_result else "missing_verifier"
    return {
        "event_type": "verifier_result",
        "data": {
            "step_title": step.get("title"),
            "tool_name": step.get("tool_name"),
            "outcome": outcome,
            "decision_behavior": behavior,
            "evidence_complete": bool(tool_result or behavior in {"ask", "deny"}),
            "residual_risk": max(int(step.get("risk") or 0) - 1, 0) if tool_result else step.get("risk"),
            "next_action": next_action,
            "critique": "Inferred from legacy OpenClaw events.",
        },
    }


def _match_legacy_permission(
    permissions: list[dict[str, Any]],
    step: dict[str, Any],
    timestep: int,
) -> dict[str, Any] | None:
    title = step.get("title")
    tool_name = step.get("tool_name")
    for event in permissions:
        data = event.get("data", {})
        decision = data.get("decision") or {}
        if data.get("step_title") == title or decision.get("tool_name") == tool_name:
            return event
    if timestep < len(permissions):
        return permissions[timestep]
    return None


def _match_legacy_tool_result(events: list[dict[str, Any]], step: dict[str, Any]) -> dict[str, Any] | None:
    tool_name = step.get("tool_name")
    for event in events:
        if event.get("event_type") != "tool_result":
            continue
        if event.get("data", {}).get("tool_name") == tool_name:
            return event
    return None


def _first_event(
    events: list[dict[str, Any]],
    event_type: str,
    *,
    subtask_id: str | None = None,
) -> dict[str, Any] | None:
    for event in events:
        if event.get("event_type") != event_type:
            continue
        if subtask_id is not None and event.get("data", {}).get("subtask_id") != subtask_id:
            continue
        return event
    return None


def _fallback_next_action(permission_data: dict[str, Any]) -> str:
    behavior = permission_data.get("behavior")
    if behavior == "ask":
        return "await_human"
    if behavior == "deny":
        return "replan"
    return "next_subtask"


def _source_meta(events_path: Path) -> dict[str, Any]:
    parts = events_path.parts
    meta: dict[str, Any] = {
        "events_path": str(events_path),
        "run_id": events_path.parent.name,
    }
    if "artifacts" in parts:
        index = parts.index("artifacts")
        if len(parts) > index + 4:
            meta.update({
                "benchmark_run": parts[index - 1] if index > 0 else None,
                "strategy": parts[index + 1],
                "task_id": parts[index + 2],
                "repeat": parts[index + 3],
            })
    return meta


def _episode_id(events_path: Path, state: dict[str, Any], source_meta: dict[str, Any]) -> str:
    digest = hashlib.sha1(
        json.dumps({
            "events_path": str(events_path),
            "run_id": source_meta.get("run_id"),
            "goal": state.get("goal"),
        }, sort_keys=True, ensure_ascii=False).encode("utf-8"),
    ).hexdigest()[:16]
    parts = [
        "openclaw",
        str(source_meta.get("benchmark_run") or "runtime"),
        str(source_meta.get("strategy") or state.get("planner_strategy") or "planner"),
        str(source_meta.get("task_id") or source_meta.get("run_id") or "run"),
        digest,
    ]
    return "/".join(_safe_path_part(part) for part in parts)


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        with path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    raise ValueError(f"Invalid JSON in {path}:{line_number}") from exc
    except FileNotFoundError:
        return []
    return rows


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _shorten(text: str, max_chars: int = MAX_TEXT_CHARS) -> str:
    text = text.strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 20].rstrip() + "\n...[truncated]"


def _safe_arg(value: Any) -> str:
    text = str(value or "unknown")
    text = re.sub(r"[^A-Za-z0-9_.:+/-]+", "_", text)
    return text.strip("_") or "unknown"


def _safe_path_part(value: Any) -> str:
    text = str(value or "unknown")
    text = text.replace("/", "_")
    return re.sub(r"[^A-Za-z0-9_.:-]+", "_", text).strip("_") or "unknown"


if __name__ == "__main__":
    main()
