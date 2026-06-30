#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from evaluate_architecture_policy import (  # noqa: E402
    IM_END,
    canonical_context_policy,
    canonical_executor_kind,
    canonical_model_tier,
    canonical_next_action,
    normalize_policy_json,
    parse_assistant_json,
    string_or_none,
)


AGENT_PLANNER_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = (
    AGENT_PLANNER_ROOT
    / "eval_runs"
    / "20260630T_architecture_policy_compact_continue200_eval95"
    / "generations.jsonl"
)
DEFAULT_OUTPUT = (
    AGENT_PLANNER_ROOT
    / "eval_runs"
    / "20260630T_architecture_policy_compact_continue200_eval95"
    / "wrapped_generations.jsonl"
)

TOOL_PRIORS = {
    "command_runner": {"model_tier": "medium", "executor_kind": "workspace_tool"},
    "deploy_runner": {"model_tier": "large", "executor_kind": "workspace_tool"},
    "file_writer": {"model_tier": "medium", "executor_kind": "workspace_tool"},
    "goal_analyzer": {"model_tier": "small", "executor_kind": "read_only_agent", "next_action": "next_subtask"},
    "mcp_tool_runner": {"model_tier": "medium", "executor_kind": "external_tool"},
    "mobile_cli_runner": {"model_tier": "medium", "executor_kind": "external_tool"},
    "mobile_gui_runner": {"model_tier": "medium", "executor_kind": "external_tool"},
    "planner": {"model_tier": "small", "executor_kind": "read_only_agent", "next_action": "next_subtask"},
    "risk_model": {"model_tier": "small", "executor_kind": "policy_gate", "next_action": "next_subtask"},
    "safety_guard": {"model_tier": "medium", "executor_kind": "policy_gate", "next_action": "next_subtask"},
    "verifier": {"model_tier": "medium", "executor_kind": "verifier", "next_action": "next_subtask"},
    "workspace_inspector": {"model_tier": "small", "executor_kind": "read_only_agent", "next_action": "next_subtask"},
}
VARIABLE_EXECUTION_TOOLS = {
    "command_runner",
    "file_writer",
    "mcp_tool_runner",
    "mobile_cli_runner",
    "mobile_gui_runner",
}
PERMISSION_NEXT_ACTION_GUARDS = {
    "ACCEPT_EDITS": "next_subtask",
    "DEFAULT": "await_human",
    "DONT_ASK": "replan",
    "EXPLORE": "replan",
}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Apply serving-time canonicalization and tool priors to compact architecture-policy generations.",
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--summary-output", type=Path, default=None)
    parser.add_argument(
        "--eval-samples",
        type=Path,
        default=None,
        help="Optional eval_samples.jsonl containing full prompts keyed by line_number.",
    )
    parser.add_argument(
        "--disable-next-action-priors",
        action="store_true",
        help="Do not apply deterministic next_action priors for tools that are always next_subtask in native data.",
    )
    args = parser.parse_args()

    stats = wrap_file(
        args.input,
        args.output,
        eval_samples_path=args.eval_samples,
        apply_next_action_priors=not args.disable_next_action_priors,
    )
    summary_output = args.summary_output or args.output.with_suffix(args.output.suffix + ".summary.json")
    summary_output.parent.mkdir(parents=True, exist_ok=True)
    summary_output.write_text(json.dumps(stats, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=False, indent=2))


def wrap_file(
    input_path: Path,
    output_path: Path,
    *,
    eval_samples_path: Path | None = None,
    apply_next_action_priors: bool = True,
) -> dict[str, Any]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    stats: Counter[str] = Counter()
    rule_counts: Counter[str] = Counter()
    eval_samples = load_eval_samples(eval_samples_path) if eval_samples_path else {}
    with input_path.open(encoding="utf-8") as input_handle, output_path.open("w", encoding="utf-8") as output_handle:
        for line_number, line in enumerate(input_handle, start=1):
            if not line.strip():
                continue
            stats["rows_seen"] += 1
            row = json.loads(line)
            sample = eval_samples.get(row.get("line_number") or line_number)
            if sample:
                row = merge_eval_sample_context(row, sample)
            wrapped, row_rules = wrap_generation_row(
                row,
                apply_next_action_priors=apply_next_action_priors,
            )
            wrapped["wrapper_rules"] = row_rules
            wrapped["wrapper_line_number"] = line_number
            output_handle.write(json.dumps(wrapped, ensure_ascii=False, separators=(",", ":")) + "\n")
            stats["rows_written"] += 1
            for rule in row_rules:
                rule_counts[rule] += 1

    return {
        "input": str(input_path),
        "output": str(output_path),
        "eval_samples": str(eval_samples_path) if eval_samples_path else None,
        "rows_seen": stats["rows_seen"],
        "rows_written": stats["rows_written"],
        "apply_next_action_priors": apply_next_action_priors,
        "rule_counts": dict(sorted(rule_counts.items())),
    }


def wrap_generation_row(
    row: dict[str, Any],
    *,
    apply_next_action_priors: bool = True,
) -> tuple[dict[str, Any], list[str]]:
    assistant_text = row.get("generated_text") or row.get("prediction") or row.get("assistant")
    parsed = parse_assistant_json(assistant_text) if isinstance(assistant_text, str) else None
    full, _normalized = normalize_policy_json(parsed)
    compact, rules = compact_from_full_policy(
        full,
        permission_mode=permission_mode_for_row(row),
        apply_next_action_priors=apply_next_action_priors,
    )

    wrapped = dict(row)
    wrapped["raw_generated_text"] = row.get("generated_text")
    wrapped["generated_text"] = json.dumps(compact, ensure_ascii=False, separators=(",", ":")) + IM_END
    wrapped["architecture_policy"] = compact
    return wrapped, rules


def compact_from_full_policy(
    parsed: dict[str, Any] | None,
    *,
    permission_mode: str | None = None,
    apply_next_action_priors: bool = True,
) -> tuple[dict[str, str], list[str]]:
    architecture = parsed.get("architecture") if isinstance(parsed, dict) and isinstance(parsed.get("architecture"), dict) else {}
    verifier = parsed.get("verifier") if isinstance(parsed, dict) and isinstance(parsed.get("verifier"), dict) else {}
    tool_name = canonical_tool_name(string_or_none(architecture.get("tool_name")) or "planner")
    rules: list[str] = []

    model_tier = canonical_model_tier(string_or_none(architecture.get("model_tier"))) or "unknown"
    context_policy = canonical_context_policy(string_or_none(architecture.get("context_policy"))) or "unknown"
    executor_kind = canonical_executor_kind(string_or_none(architecture.get("executor_kind"))) or "unknown"
    next_action = (
        canonical_next_action(
            string_or_none(verifier.get("next_action"))
            or string_or_none(architecture.get("expected_next_action"))
        )
        or "unknown"
    )

    prior = TOOL_PRIORS.get(tool_name, {})
    if prior.get("model_tier") and prior["model_tier"] != model_tier:
        model_tier = prior["model_tier"]
        rules.append("tool_prior:model_tier")
    if prior.get("executor_kind") and prior["executor_kind"] != executor_kind:
        executor_kind = prior["executor_kind"]
        rules.append("tool_prior:executor_kind")
    if apply_next_action_priors and prior.get("next_action") and prior["next_action"] != next_action:
        next_action = prior["next_action"]
        rules.append("tool_prior:next_action")
    guarded_next_action = permission_guard_next_action(permission_mode, tool_name, next_action)
    if guarded_next_action != next_action:
        next_action = guarded_next_action
        rules.append(f"permission_guard:next_action:{permission_mode}")

    return {
        "task_id": string_or_none(architecture.get("task_id")) or "unknown",
        "tool_name": tool_name,
        "model_tier": model_tier,
        "context_policy": context_policy,
        "executor_kind": executor_kind,
        "verifier_next_action": next_action,
    }, rules


def canonical_tool_name(value: str) -> str:
    return value.strip().lower().replace("-", "_")


def permission_guard_next_action(permission_mode: str | None, tool_name: str, next_action: str) -> str:
    if tool_name not in VARIABLE_EXECUTION_TOOLS:
        return next_action
    if permission_mode not in PERMISSION_NEXT_ACTION_GUARDS:
        return next_action
    return PERMISSION_NEXT_ACTION_GUARDS[permission_mode]


def permission_mode_for_row(row: dict[str, Any]) -> str | None:
    value = row.get("permission_mode")
    if isinstance(value, str) and value:
        return value

    for key in ("task_preview", "prompt", "input", "user"):
        text = row.get(key)
        if not isinstance(text, str):
            continue
        match = re.search(r"Permission mode:\s*([A-Z_]+)", text)
        if match:
            return match.group(1)
    return None


def load_eval_samples(path: Path | None) -> dict[int, dict[str, Any]]:
    if path is None:
        return {}
    samples: dict[int, dict[str, Any]] = {}
    with path.open(encoding="utf-8") as handle:
        for fallback_line, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            line_number = row.get("line_number")
            if not isinstance(line_number, int):
                line_number = fallback_line
            samples[line_number] = row
    return samples


def merge_eval_sample_context(row: dict[str, Any], sample: dict[str, Any]) -> dict[str, Any]:
    merged = dict(row)
    for key in ("prompt", "task_preview", "permission_mode"):
        value = sample.get(key)
        if isinstance(value, str) and value:
            merged[key] = value
    return merged


if __name__ == "__main__":
    main()
