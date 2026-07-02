#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
AGENT_PLANNER_ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from evaluate_architecture_policy import IM_END, iter_jsonl, load_references  # noqa: E402
from evaluate_planner_sft import split_sft_text  # noqa: E402


DEFAULT_MATRIX = (
    AGENT_PLANNER_ROOT
    / "eval_runs"
    / "20260701T_stage16_runtime_shadow_matrix_1k"
    / "shadow_matrix_rows.jsonl"
)
DEFAULT_EVAL_SAMPLES = (
    AGENT_PLANNER_ROOT
    / "eval_runs"
    / "20260701T_architecture_policy_model_stage14_r2_1k"
    / "eval_samples.jsonl"
)
DEFAULT_OUTPUT = AGENT_PLANNER_ROOT / "processed" / "stage16_architecture_rule_distillation_sft.jsonl"


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Build compact architecture-policy SFT rows from runtime shadow matrix corrections. "
            "Rows are selected where the raw learned model would change runtime behavior and the "
            "chosen teacher predictor is exact."
        ),
    )
    parser.add_argument("--matrix-rows", type=Path, default=DEFAULT_MATRIX)
    parser.add_argument("--eval-samples", type=Path, default=DEFAULT_EVAL_SAMPLES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--summary-output", type=Path, default=None)
    parser.add_argument("--key-field", default="line_number")
    parser.add_argument(
        "--teacher",
        choices=("classifier", "wrapped"),
        default="classifier",
        help="Teacher prediction to distill when raw is wrong.",
    )
    parser.add_argument(
        "--include-wrapper-rule-rows",
        action="store_true",
        help="Also include rows with wrapper rules even if raw is already exact.",
    )
    parser.add_argument("--max-rows", type=int, default=0)
    args = parser.parse_args()

    summary = build_distillation_file(
        matrix_rows=args.matrix_rows,
        eval_samples=args.eval_samples,
        output_path=args.output,
        summary_output_path=args.summary_output,
        key_field=args.key_field,
        teacher=args.teacher,
        include_wrapper_rule_rows=args.include_wrapper_rule_rows,
        max_rows=args.max_rows,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def build_distillation_file(
    *,
    matrix_rows: Path,
    eval_samples: Path,
    output_path: Path,
    summary_output_path: Path | None = None,
    key_field: str = "line_number",
    teacher: str = "classifier",
    include_wrapper_rule_rows: bool = False,
    max_rows: int = 0,
) -> dict[str, Any]:
    samples = load_references(eval_samples, key_field=key_field)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    stats: Counter[str] = Counter()
    mismatch_fields: Counter[str] = Counter()
    wrapper_rules: Counter[str] = Counter()
    tool_counts: Counter[str] = Counter()
    permission_counts: Counter[str] = Counter()

    with output_path.open("w", encoding="utf-8") as output_handle:
        for _line_number, row in iter_jsonl(matrix_rows):
            if max_rows and stats["rows_written"] >= max_rows:
                break
            stats["rows_seen"] += 1
            if not should_distill(row, teacher=teacher, include_wrapper_rule_rows=include_wrapper_rule_rows):
                stats["rows_skipped"] += 1
                continue
            key = row.get("key")
            sample = samples.get(key)
            if sample is None:
                stats["missing_sample"] += 1
                continue
            prompt = prompt_from_sample(sample)
            if not prompt:
                stats["missing_prompt"] += 1
                continue
            target = compact_target(row, teacher=teacher)
            output_row = {
                "source": "openclaw_architecture_rule_distillation",
                "format": "openclaw_architecture_compact_sft_text",
                "line_number": stats["rows_written"] + 1,
                "source_key": key,
                "source_transition_id": row.get("transition_id"),
                "source_mode": "stage16_rule_distillation",
                "balance_stratum": (
                    f"stage16_rule_distillation|teacher={teacher}|"
                    f"tool={row.get('tool_name')}|permission={row.get('permission_mode')}"
                ),
                "teacher": teacher,
                "tool_name": row.get("tool_name"),
                "permission_mode": row.get("permission_mode"),
                "expected": expected_for_output(row),
                "raw_prediction": row.get("predictions", {}).get("raw"),
                "teacher_prediction": row.get("predictions", {}).get(teacher),
                "raw_matches": row.get("matches", {}).get("raw"),
                "teacher_matches": row.get("matches", {}).get(teacher),
                "wrapper_rules": row.get("wrapper_rules") or [],
                "target": json.dumps(target, ensure_ascii=False, separators=(",", ":")) + IM_END,
                "text": prompt + json.dumps(target, ensure_ascii=False, separators=(",", ":")) + IM_END + "\n",
            }
            output_handle.write(json.dumps(output_row, ensure_ascii=False, separators=(",", ":")) + "\n")
            stats["rows_written"] += 1
            tool_counts[str(row.get("tool_name") or "unknown")] += 1
            permission_counts[str(row.get("permission_mode") or "UNKNOWN")] += 1
            for rule in row.get("wrapper_rules") or []:
                wrapper_rules[str(rule)] += 1
            for field, matched in (row.get("matches", {}).get("raw") or {}).items():
                if not matched:
                    mismatch_fields[field] += 1

    summary = {
        "created_at": utc_now(),
        "matrix_rows": str(matrix_rows),
        "eval_samples": str(eval_samples),
        "output": str(output_path),
        "teacher": teacher,
        "include_wrapper_rule_rows": include_wrapper_rule_rows,
        "key_field": key_field,
        "stats": dict(sorted(stats.items())),
        "raw_mismatch_fields": dict(sorted(mismatch_fields.items())),
        "wrapper_rule_counts": dict(sorted(wrapper_rules.items())),
        "tool_counts": dict(sorted(tool_counts.items())),
        "permission_mode_counts": dict(sorted(permission_counts.items())),
    }
    summary_path = summary_output_path or output_path.with_suffix(output_path.suffix + ".summary.json")
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary["summary_output"] = str(summary_path)
    return summary


def should_distill(
    row: dict[str, Any],
    *,
    teacher: str,
    include_wrapper_rule_rows: bool,
) -> bool:
    exact = row.get("exact_match") if isinstance(row.get("exact_match"), dict) else {}
    if exact.get(teacher) is not True:
        return False
    raw_wrong = exact.get("raw") is False
    if raw_wrong:
        return True
    return include_wrapper_rule_rows and bool(row.get("wrapper_rules"))


def prompt_from_sample(sample: dict[str, Any]) -> str:
    prompt = sample.get("prompt")
    if isinstance(prompt, str) and prompt:
        return prompt
    text = sample.get("text")
    if isinstance(text, str):
        split = split_sft_text(text)
        if split is not None:
            return split[0]
    return ""


def compact_target(row: dict[str, Any], *, teacher: str) -> dict[str, str]:
    prediction = (row.get("predictions") or {}).get(teacher) or {}
    expected = row.get("expected") or {}
    return {
        "task_id": str(prediction.get("task_id") or row.get("task_id") or "unknown"),
        "tool_name": str(prediction.get("tool_name") or row.get("tool_name") or "planner"),
        "model_tier": str(prediction.get("model_tier") or expected.get("model_tier") or "unknown"),
        "context_policy": str(prediction.get("context_policy") or expected.get("context_policy") or "unknown"),
        "executor_kind": str(prediction.get("executor_kind") or expected.get("executor_kind") or "unknown"),
        "verifier_next_action": str(
            prediction.get("verifier_next_action")
            or expected.get("verifier_next_action")
            or "unknown"
        ),
    }


def expected_for_output(row: dict[str, Any]) -> dict[str, str]:
    expected = row.get("expected") or {}
    return {
        "model_tier": str(expected.get("model_tier") or "unknown"),
        "next_action": str(expected.get("next_action") or expected.get("verifier_next_action") or "unknown"),
        "context_policy": str(expected.get("context_policy") or "unknown"),
        "executor_kind": str(expected.get("executor_kind") or "unknown"),
    }


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    main()
