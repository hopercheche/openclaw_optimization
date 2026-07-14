#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
AGENT_PLANNER_ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from architecture_policy import (  # noqa: E402
    POLICY_FIELDS,
    permission_mode_for_row,
    policy_context_for_row,
    policy_from_tool_context,
    score_compact_policy,
)
from evaluate_planner_sft import split_sft_text  # noqa: E402


DEFAULT_INPUT = AGENT_PLANNER_ROOT / "processed" / "openclaw_architecture_stage14_r2_compact_eval.jsonl"
DEFAULT_OUTPUT_DIR = AGENT_PLANNER_ROOT / "eval_runs" / "architecture_policy_classifier"
LAYER_FIELDS = {
    "strategist": ("model_tier", "verifier_next_action"),
    "architect": ("context_policy", "executor_kind"),
}


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate a zero-generation architecture-policy enum classifier baseline. "
            "This is a lower-latency alternative to JSON generation and a target for future distillation."
        ),
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--max-rows", type=int, default=0)
    parser.add_argument(
        "--disable-next-action-priors",
        action="store_true",
        help="Disable deterministic next_action priors to measure field-classifier dependence on guards.",
    )
    args = parser.parse_args()

    metrics = evaluate_classifier(
        input_path=args.input,
        output_dir=args.output_dir,
        max_rows=args.max_rows,
        apply_next_action_priors=not args.disable_next_action_priors,
    )
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


def evaluate_classifier(
    *,
    input_path: Path,
    output_dir: Path,
    max_rows: int = 0,
    apply_next_action_priors: bool = True,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    predictions_path = output_dir / "classifier_predictions.jsonl"
    stats: Counter[str] = Counter()
    field_correct: Counter[str] = Counter()
    field_total: Counter[str] = Counter()
    layer_correct: Counter[str] = Counter()
    layer_total: Counter[str] = Counter()
    rule_counts: Counter[str] = Counter()
    by_tool: dict[str, Counter[str]] = {}
    by_permission: dict[str, Counter[str]] = {}
    mismatches: list[dict[str, Any]] = []
    elapsed_predict = 0.0

    with input_path.open(encoding="utf-8") as input_handle, predictions_path.open("w", encoding="utf-8") as output_handle:
        for line_number, line in enumerate(input_handle, start=1):
            if max_rows and stats["rows"] >= max_rows:
                break
            if not line.strip():
                continue
            row = json.loads(line)
            prompt = prompt_from_sft_row(row)
            if prompt is None:
                stats["rows_skipped"] += 1
                continue
            classifier_row = {
                "prompt": prompt,
                "task_preview": row.get("task_preview") if isinstance(row.get("task_preview"), str) else "",
            }
            started = time.perf_counter()
            context = policy_context_for_row(classifier_row)
            prediction, rules = policy_from_tool_context(
                tool_name=context.get("tool_name") or "planner",
                permission_mode=permission_mode_for_row(classifier_row),
                task_id=context.get("task_id") or "unknown",
                action=context.get("action") or "",
                apply_next_action_priors=apply_next_action_priors,
            )
            elapsed_predict += time.perf_counter() - started
            expected = expected_policy(row)
            score = score_compact_policy(prediction, expected)
            layer_matches = layer_match_summary(score["matches"])

            stats["rows"] += 1
            if score["exact_match"]:
                stats["exact_matches"] += 1
            for field, matched in score["matches"].items():
                field_total[field] += 1
                if matched:
                    field_correct[field] += 1
            for layer, matched in layer_matches.items():
                layer_total[layer] += 1
                if matched:
                    layer_correct[layer] += 1
            for rule in rules:
                rule_counts[rule] += 1
            update_group(by_tool, prediction["tool_name"], score)
            update_group(by_permission, permission_mode_for_row(classifier_row) or "UNKNOWN", score)
            record = {
                "line_number": line_number,
                "transition_id": row.get("transition_id"),
                "permission_mode": permission_mode_for_row(classifier_row),
                "prediction": prediction,
                "expected": expected,
                "matches": score["matches"],
                "layer_matches": layer_matches,
                "exact_match": score["exact_match"],
                "rules": rules,
            }
            if not score["exact_match"] and len(mismatches) < 40:
                mismatches.append(record)
            output_handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")

    metrics = {
        "created_at": utc_now(),
        "input": str(input_path),
        "output_dir": str(output_dir),
        "predictions_jsonl": str(predictions_path),
        "apply_next_action_priors": apply_next_action_priors,
        "overall": finalize(stats, field_correct, field_total, layer_correct, layer_total, elapsed_predict),
        "rule_counts": dict(sorted(rule_counts.items())),
        "by_tool": finalize_groups(by_tool),
        "by_permission_mode": finalize_groups(by_permission),
        "mismatch_examples": mismatches,
    }
    metrics_path = output_dir / "metrics.json"
    report_path = output_dir / "report.md"
    metrics_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report_path.write_text(render_report(metrics), encoding="utf-8")
    metrics["outputs"] = {
        "metrics_json": str(metrics_path),
        "report_md": str(report_path),
    }
    return metrics


def prompt_from_sft_row(row: dict[str, Any]) -> str | None:
    text = row.get("text")
    if not isinstance(text, str):
        return None
    split = split_sft_text(text)
    if split is None:
        return None
    return split[0]


def expected_policy(row: dict[str, Any]) -> dict[str, str]:
    expected = row.get("expected") if isinstance(row.get("expected"), dict) else {}
    text = row.get("text") if isinstance(row.get("text"), str) else ""
    assistant = split_sft_text(text)[1] if split_sft_text(text) else "{}"
    parsed = safe_json(assistant)
    return {
        "model_tier": str(expected.get("model_tier") or parsed.get("model_tier") or "unknown"),
        "verifier_next_action": str(expected.get("next_action") or parsed.get("verifier_next_action") or "unknown"),
        "context_policy": str(expected.get("context_policy") or parsed.get("context_policy") or "unknown"),
        "executor_kind": str(expected.get("executor_kind") or parsed.get("executor_kind") or "unknown"),
    }


def safe_json(text: str) -> dict[str, Any]:
    cleaned = text.replace("<|im_end|>", "").strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end < start:
        return {}
    try:
        parsed = json.loads(cleaned[start:end + 1])
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def update_group(groups: dict[str, Counter[str]], key: str, score: dict[str, Any]) -> None:
    group = groups.setdefault(key or "__missing__", Counter())
    group["rows"] += 1
    if score["exact_match"]:
        group["exact_matches"] += 1
    for field, matched in score["matches"].items():
        group[f"{field}_total"] += 1
        if matched:
            group[f"{field}_correct"] += 1


def layer_match_summary(field_matches: dict[str, bool]) -> dict[str, bool]:
    return {
        layer: all(field_matches.get(field) for field in fields)
        for layer, fields in LAYER_FIELDS.items()
    }


def finalize(
    stats: Counter[str],
    field_correct: Counter[str],
    field_total: Counter[str],
    layer_correct: Counter[str],
    layer_total: Counter[str],
    elapsed_predict: float,
) -> dict[str, Any]:
    rows = stats["rows"]
    output: dict[str, Any] = {
        "rows": rows,
        "rows_skipped": stats["rows_skipped"],
        "exact_matches": stats["exact_matches"],
        "exact_match_rate": rate(stats["exact_matches"], rows),
        "total_prediction_seconds": round(elapsed_predict, 6),
        "mean_prediction_seconds": round(elapsed_predict / rows, 8) if rows else 0.0,
    }
    for field in POLICY_FIELDS:
        correct = field_correct[field]
        total = field_total[field]
        output[f"{field}_correct"] = correct
        output[f"{field}_total"] = total
        output[f"{field}_accuracy"] = rate(correct, total)
    for layer in LAYER_FIELDS:
        correct = layer_correct[layer]
        total = layer_total[layer]
        output[f"{layer}_exact_correct"] = correct
        output[f"{layer}_exact_total"] = total
        output[f"{layer}_exact_rate"] = rate(correct, total)
    return output


def finalize_groups(groups: dict[str, Counter[str]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key, counter in sorted(groups.items()):
        rows = counter["rows"]
        item: dict[str, Any] = {
            "rows": rows,
            "exact_match_rate": rate(counter["exact_matches"], rows),
        }
        for field in POLICY_FIELDS:
            item[f"{field}_accuracy"] = rate(counter[f"{field}_correct"], counter[f"{field}_total"])
        output[key] = item
    return output


def render_report(metrics: dict[str, Any]) -> str:
    overall = metrics["overall"]
    lines = [
        "# Architecture-Policy Enum Classifier Benchmark",
        "",
        f"- Input: `{metrics['input']}`",
        f"- Rows: {overall['rows']}",
        f"- Exact match: {overall['exact_match_rate']:.2%}",
        f"- Mean prediction seconds: {overall['mean_prediction_seconds']}",
        "",
        "| Field | Accuracy |",
        "| --- | ---: |",
    ]
    for field in POLICY_FIELDS:
        lines.append(f"| {field} | {overall[f'{field}_accuracy']:.2%} |")
    lines.extend(["", "## Architecture Layers", "", "| Layer | Exact |", "| --- | ---: |"])
    for layer in LAYER_FIELDS:
        lines.append(f"| {layer} | {overall[f'{layer}_exact_rate']:.2%} |")
    lines.extend(["", "## Rules", ""])
    if metrics["rule_counts"]:
        lines.extend(f"- `{rule}`: {count}" for rule, count in metrics["rule_counts"].items())
    else:
        lines.append("- No rules fired.")
    return "\n".join(lines) + "\n"


def rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    main()
