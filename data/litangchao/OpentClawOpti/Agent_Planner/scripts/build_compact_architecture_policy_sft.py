#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


AGENT_PLANNER_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TRAIN_INPUT = AGENT_PLANNER_ROOT / "processed" / "openclaw_architecture_native_balanced_train.jsonl"
DEFAULT_HELDOUT_INPUT = AGENT_PLANNER_ROOT / "processed" / "openclaw_architecture_native_balanced_holdout.jsonl"
DEFAULT_TRAIN_OUTPUT = AGENT_PLANNER_ROOT / "processed" / "openclaw_architecture_native_compact_train.jsonl"
DEFAULT_HELDOUT_OUTPUT = AGENT_PLANNER_ROOT / "processed" / "openclaw_architecture_native_compact_holdout.jsonl"
ASSISTANT_MARKER = "<|im_start|>assistant\n"
IM_END = "<|im_end|>"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build compact architecture-policy SFT rows from OpenClaw full architecture SFT rows.",
    )
    parser.add_argument("--train-input", type=Path, default=DEFAULT_TRAIN_INPUT)
    parser.add_argument("--heldout-input", type=Path, default=DEFAULT_HELDOUT_INPUT)
    parser.add_argument("--train-output", type=Path, default=DEFAULT_TRAIN_OUTPUT)
    parser.add_argument("--heldout-output", type=Path, default=DEFAULT_HELDOUT_OUTPUT)
    parser.add_argument(
        "--target-mode",
        choices=("compact", "wrapped"),
        default="compact",
        help="compact emits only policy fields; wrapped emits a minimal full architecture schema.",
    )
    args = parser.parse_args()

    stats = {
        "train": convert_file(args.train_input, args.train_output, target_mode=args.target_mode),
        "heldout": convert_file(args.heldout_input, args.heldout_output, target_mode=args.target_mode),
        "target_mode": args.target_mode,
    }
    print(json.dumps(stats, ensure_ascii=False, indent=2))


def convert_file(input_path: Path, output_path: Path, *, target_mode: str = "compact") -> dict[str, Any]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    stats = {
        "input": str(input_path),
        "output": str(output_path),
        "rows_seen": 0,
        "rows_written": 0,
        "rows_skipped": 0,
        "skip_reasons": {},
    }
    with input_path.open(encoding="utf-8") as input_handle, output_path.open("w", encoding="utf-8") as output_handle:
        for line_number, line in enumerate(input_handle, start=1):
            if not line.strip():
                continue
            stats["rows_seen"] += 1
            row = json.loads(line)
            converted, reason = compact_row(row, target_mode=target_mode)
            if converted is None:
                stats["rows_skipped"] += 1
                stats["skip_reasons"][reason or "unknown"] = stats["skip_reasons"].get(reason or "unknown", 0) + 1
                continue
            converted["compact_source_line"] = line_number
            output_handle.write(json.dumps(converted, ensure_ascii=False, separators=(",", ":")) + "\n")
            stats["rows_written"] += 1
    return stats


def compact_row(row: dict[str, Any], *, target_mode: str = "compact") -> tuple[dict[str, Any] | None, str | None]:
    text = row.get("text")
    if not isinstance(text, str):
        return None, "missing_text"
    prompt, assistant_text = split_prompt_and_assistant(text)
    if prompt is None or assistant_text is None:
        return None, "missing_assistant_marker"
    parsed = parse_json_object(assistant_text)
    if not isinstance(parsed, dict):
        return None, "invalid_assistant_json"
    architecture = parsed.get("architecture")
    verifier = parsed.get("verifier")
    if not isinstance(architecture, dict) or not isinstance(verifier, dict):
        return None, "missing_architecture_or_verifier"

    target = build_target(parsed, architecture, verifier, target_mode=target_mode)
    converted = dict(row)
    converted["format"] = f"openclaw_architecture_{target_mode}_sft_text"
    converted["text"] = f"{prompt}{json.dumps(target, ensure_ascii=False, separators=(',', ':'))}{IM_END}\n"
    converted["expected"] = {
        "model_tier": target["model_tier"] if target_mode == "compact" else target["architecture"]["model_tier"],
        "next_action": (
            target["verifier_next_action"]
            if target_mode == "compact"
            else target["verifier"]["next_action"]
        ),
        "context_policy": (
            target["context_policy"]
            if target_mode == "compact"
            else target["architecture"]["context_policy"]
        ),
        "executor_kind": (
            target["executor_kind"]
            if target_mode == "compact"
            else target["architecture"]["executor_kind"]
        ),
    }
    converted["target_mode"] = target_mode
    return converted, None


def split_prompt_and_assistant(text: str) -> tuple[str | None, str | None]:
    marker_index = text.rfind(ASSISTANT_MARKER)
    if marker_index < 0:
        return None, None
    prompt = text[: marker_index + len(ASSISTANT_MARKER)]
    completion = text[marker_index + len(ASSISTANT_MARKER):].strip()
    if completion.endswith(IM_END):
        completion = completion[: -len(IM_END)].strip()
    return prompt, completion


def parse_json_object(text: str) -> dict[str, Any] | None:
    cleaned = re.sub(r"<think>.*?</think>", "", text.replace(IM_END, ""), flags=re.DOTALL)
    start = cleaned.find("{")
    if start < 0:
        return None
    candidate = extract_json_object(cleaned, start)
    if candidate is None:
        return None
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def extract_json_object(text: str, start: int) -> str | None:
    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start:index + 1]
    return None


def build_target(
    full_target: dict[str, Any],
    architecture: dict[str, Any],
    verifier: dict[str, Any],
    *,
    target_mode: str,
) -> dict[str, Any]:
    next_action = string_value(verifier.get("next_action")) or string_value(architecture.get("expected_next_action"))
    compact = {
        "task_id": string_value(architecture.get("task_id")) or "unknown",
        "tool_name": string_value(architecture.get("tool_name")) or "planner",
        "model_tier": string_value(architecture.get("model_tier")) or "unknown",
        "context_policy": string_value(architecture.get("context_policy")) or "unknown",
        "executor_kind": string_value(architecture.get("executor_kind")) or "unknown",
        "verifier_next_action": next_action or "unknown",
    }
    if target_mode == "compact":
        return compact

    command = (
        "openclaw.plan_subtask "
        f"--tool {safe_arg(compact['tool_name'])} "
        f"--model-tier {safe_arg(compact['model_tier'])} "
        f"--context-policy {safe_arg(compact['context_policy'])} "
        f"--next-action {safe_arg(compact['verifier_next_action'])}"
    )
    return {
        "analysis": (
            f"Select {compact['tool_name']} with {compact['model_tier']} model and "
            f"{compact['context_policy']} context."
        ),
        "plan": (
            f"Executor kind is {compact['executor_kind']}; "
            f"verifier next_action is {compact['verifier_next_action']}."
        ),
        "commands": [{"keystrokes": command, "duration": 1}],
        "task_complete": bool(full_target.get("task_complete")),
        "architecture": {
            "task_id": compact["task_id"],
            "tool_name": compact["tool_name"],
            "action": string_value(architecture.get("action")) or "",
            "model_tier": compact["model_tier"],
            "risk_level": string_value(architecture.get("risk_level")) or "unknown",
            "context_policy": compact["context_policy"],
            "memory_queries": architecture.get("memory_queries") if isinstance(architecture.get("memory_queries"), list) else [],
            "success_criteria": (
                architecture.get("success_criteria")
                if isinstance(architecture.get("success_criteria"), list)
                else []
            ),
            "executor_kind": compact["executor_kind"],
            "expected_next_action": compact["verifier_next_action"],
        },
        "verifier": {
            "outcome": string_value(verifier.get("outcome")) or "unknown",
            "decision_behavior": string_value(verifier.get("decision_behavior")) or "unknown",
            "next_action": compact["verifier_next_action"],
            "evidence_complete": bool(verifier.get("evidence_complete", True)),
            "residual_risk": verifier.get("residual_risk"),
            "critique": string_value(verifier.get("critique")) or "",
        },
    }


def string_value(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def safe_arg(value: Any) -> str:
    text = str(value or "unknown")
    text = re.sub(r"[^A-Za-z0-9_.:+/-]+", "_", text)
    return text.strip("_") or "unknown"


if __name__ == "__main__":
    main()
