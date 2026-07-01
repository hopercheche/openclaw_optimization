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

from architecture_policy import canonical_tool_name, wrap_generation_row  # noqa: E402
from evaluate_architecture_policy import (  # noqa: E402
    POLICY_FIELDS,
    evaluate_row,
    iter_jsonl,
    load_references,
    parse_assistant_json,
    policy_predictions,
    reference_key,
    strip_im_end,
    normalize_policy_json,
)


DEFAULT_REFERENCE = AGENT_PLANNER_ROOT / "processed" / "openclaw_architecture_stage14_r2_compact_eval.jsonl"
DEFAULT_RAW = (
    AGENT_PLANNER_ROOT
    / "eval_runs"
    / "20260701T_architecture_policy_model_stage14_r2_1k"
    / "generations.jsonl"
)
DEFAULT_OUTPUT_DIR = AGENT_PLANNER_ROOT / "eval_runs" / "architecture_policy_runtime_shadow"


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Compare raw learned architecture-policy generations against the serving wrapper "
            "as a runtime-shadow readiness report."
        ),
    )
    parser.add_argument("--raw-generations", type=Path, default=DEFAULT_RAW)
    parser.add_argument("--reference", type=Path, default=DEFAULT_REFERENCE)
    parser.add_argument("--eval-samples", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--key-field", default="line_number")
    parser.add_argument("--max-rows", type=int, default=0)
    args = parser.parse_args()

    metrics = compare_runtime_shadow(
        raw_generations=args.raw_generations,
        reference=args.reference,
        output_dir=args.output_dir,
        eval_samples=args.eval_samples,
        key_field=args.key_field,
        max_rows=args.max_rows,
    )
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


def compare_runtime_shadow(
    *,
    raw_generations: Path,
    reference: Path,
    output_dir: Path,
    eval_samples: Path | None = None,
    key_field: str = "line_number",
    max_rows: int = 0,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    references = load_references(reference, key_field=key_field)
    samples = load_references(eval_samples, key_field=key_field) if eval_samples else {}
    rows_path = output_dir / "runtime_shadow_rows.jsonl"

    raw_aggregate = new_aggregate()
    wrapped_aggregate = new_aggregate()
    by_tool: dict[str, dict[str, Any]] = {}
    by_permission: dict[str, dict[str, Any]] = {}
    wrapper_rules: Counter[str] = Counter()
    repair_counts: Counter[str] = Counter()
    examples: list[dict[str, Any]] = []

    with rows_path.open("w", encoding="utf-8") as output_handle:
        for raw_line_number, raw_row in iter_jsonl(raw_generations):
            if max_rows and raw_aggregate["rows"] >= max_rows:
                break
            key = reference_key(raw_row, raw_line_number, key_field)
            reference_row = references.get(key)
            sample_row = samples.get(key)
            merged_raw = merge_context(raw_row, sample_row)
            raw_result = evaluate_row(
                raw_row,
                line_number=raw_line_number,
                reference=reference_row,
                normalize_compact=True,
            )
            wrapped_row, rules = wrap_generation_row(merged_raw)
            wrapped_result = evaluate_row(
                wrapped_row,
                line_number=raw_line_number,
                reference=reference_row,
                normalize_compact=True,
            )
            raw_prediction = extract_policy(raw_row.get("generated_text"))
            wrapped_prediction = dict(wrapped_row.get("architecture_policy") or {})
            expected = expected_from_result(wrapped_result)
            tool_name = canonical_tool_name(
                str(wrapped_prediction.get("tool_name") or raw_prediction.get("tool_name") or "unknown")
            )
            permission_mode = permission_mode_from_row(merged_raw)

            update_aggregate(raw_aggregate, raw_result)
            update_aggregate(wrapped_aggregate, wrapped_result)
            update_group(by_tool.setdefault(tool_name, new_group()), raw_result, wrapped_result)
            update_group(by_permission.setdefault(permission_mode, new_group()), raw_result, wrapped_result)
            for rule in rules:
                wrapper_rules[rule] += 1

            field_deltas = field_delta(raw_result, wrapped_result)
            for field, delta in field_deltas.items():
                repair_counts[f"{field}:{delta}"] += 1
            row_summary = {
                "line_number": raw_line_number,
                "key": key,
                "permission_mode": permission_mode,
                "tool_name": tool_name,
                "expected": expected,
                "raw_prediction": raw_prediction,
                "wrapped_prediction": wrapped_prediction,
                "raw_matches": raw_result["matches"],
                "wrapped_matches": wrapped_result["matches"],
                "field_deltas": field_deltas,
                "raw_parse_error": raw_result.get("parse_error"),
                "wrapper_rules": rules,
            }
            if any(delta != "unchanged" for delta in field_deltas.values()) and len(examples) < 40:
                examples.append(row_summary)
            output_handle.write(json.dumps(row_summary, ensure_ascii=False, separators=(",", ":")) + "\n")

    metrics = {
        "created_at": utc_now(),
        "raw_generations": str(raw_generations),
        "reference": str(reference),
        "eval_samples": str(eval_samples) if eval_samples else None,
        "key_field": key_field,
        "rows_jsonl": str(rows_path),
        "raw": finalize_aggregate(raw_aggregate),
        "wrapped": finalize_aggregate(wrapped_aggregate),
        "wrapper_rules": dict(sorted(wrapper_rules.items())),
        "repair_counts": dict(sorted(repair_counts.items())),
        "by_tool": finalize_groups(by_tool),
        "by_permission_mode": finalize_groups(by_permission),
        "delta_examples": examples,
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


def merge_context(row: dict[str, Any], sample: dict[str, Any] | None) -> dict[str, Any]:
    merged = dict(row)
    if not sample:
        return merged
    for key in ("prompt", "task_preview", "permission_mode"):
        value = sample.get(key)
        if isinstance(value, str) and value:
            merged[key] = value
    return merged


def extract_policy(text: Any) -> dict[str, Any]:
    parsed = parse_assistant_json(strip_im_end(text)) if isinstance(text, str) else None
    normalized, _ = normalize_policy_json(parsed)
    predictions = policy_predictions(normalized)
    architecture = normalized.get("architecture") if isinstance(normalized, dict) else {}
    tool_name = architecture.get("tool_name") if isinstance(architecture, dict) else None
    task_id = architecture.get("task_id") if isinstance(architecture, dict) else None
    return {
        "task_id": task_id if isinstance(task_id, str) else "unknown",
        "tool_name": tool_name if isinstance(tool_name, str) else "unknown",
        "model_tier": predictions.get("model_tier"),
        "context_policy": predictions.get("context_policy"),
        "executor_kind": predictions.get("executor_kind"),
        "verifier_next_action": predictions.get("next_action"),
    }


def expected_from_result(result: dict[str, Any]) -> dict[str, Any]:
    expected = result["expected"]
    return {
        "model_tier": expected.get("model_tier"),
        "context_policy": expected.get("context_policy"),
        "executor_kind": expected.get("executor_kind"),
        "verifier_next_action": expected.get("next_action"),
    }


def permission_mode_from_row(row: dict[str, Any]) -> str:
    for key in ("permission_mode", "prompt", "task_preview", "input", "user"):
        value = row.get(key)
        if not isinstance(value, str):
            continue
        if key == "permission_mode" and value:
            return value.upper()
        marker = "Permission mode:"
        index = value.find(marker)
        if index >= 0:
            token = value[index + len(marker):].strip().split(maxsplit=1)[0]
            return token.upper()
    return "UNKNOWN"


def new_aggregate() -> dict[str, Any]:
    return {
        "rows": 0,
        "schema_valid": 0,
        "correct": Counter(),
        "total": Counter(),
    }


def update_aggregate(aggregate: dict[str, Any], result: dict[str, Any]) -> None:
    aggregate["rows"] += 1
    aggregate["schema_valid"] += int(bool(result["schema"]["schema_valid"]))
    for field in POLICY_FIELDS:
        if result["matches"].get(field) is not None:
            aggregate["total"][field] += 1
            aggregate["correct"][field] += int(result["matches"][field] is True)


def finalize_aggregate(aggregate: dict[str, Any]) -> dict[str, Any]:
    rows = aggregate["rows"]
    output: dict[str, Any] = {
        "rows": rows,
        "schema_valid_count": aggregate["schema_valid"],
        "schema_valid_rate": rate(aggregate["schema_valid"], rows),
    }
    for field in POLICY_FIELDS:
        total = aggregate["total"][field]
        correct = aggregate["correct"][field]
        output[f"{field}_correct"] = correct
        output[f"{field}_total"] = total
        output[f"{field}_accuracy"] = rate(correct, total)
    return output


def new_group() -> dict[str, Any]:
    return {
        "raw": new_aggregate(),
        "wrapped": new_aggregate(),
        "deltas": Counter(),
    }


def update_group(group: dict[str, Any], raw_result: dict[str, Any], wrapped_result: dict[str, Any]) -> None:
    update_aggregate(group["raw"], raw_result)
    update_aggregate(group["wrapped"], wrapped_result)
    for field, delta in field_delta(raw_result, wrapped_result).items():
        group["deltas"][f"{field}:{delta}"] += 1


def finalize_groups(groups: dict[str, dict[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key, group in sorted(groups.items()):
        output[key] = {
            "raw": finalize_aggregate(group["raw"]),
            "wrapped": finalize_aggregate(group["wrapped"]),
            "deltas": dict(sorted(group["deltas"].items())),
        }
    return output


def field_delta(raw_result: dict[str, Any], wrapped_result: dict[str, Any]) -> dict[str, str]:
    deltas: dict[str, str] = {}
    for field in POLICY_FIELDS:
        raw = raw_result["matches"].get(field)
        wrapped = wrapped_result["matches"].get(field)
        if raw is True and wrapped is True:
            deltas[field] = "unchanged"
        elif raw is not True and wrapped is True:
            deltas[field] = "repaired"
        elif raw is True and wrapped is not True:
            deltas[field] = "regressed"
        else:
            deltas[field] = "still_wrong"
    return deltas


def render_report(metrics: dict[str, Any]) -> str:
    raw = metrics["raw"]
    wrapped = metrics["wrapped"]
    lines = [
        "# Architecture-Policy Runtime Shadow Compare",
        "",
        f"- Raw generations: `{metrics['raw_generations']}`",
        f"- Reference: `{metrics['reference']}`",
        f"- Rows: {raw['rows']}",
        "",
        "## Overall",
        "",
        "| Layer | Schema | Model | Next | Context | Executor |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
        metric_row("raw", raw),
        metric_row("wrapped", wrapped),
        "",
        "## Wrapper Rules",
        "",
    ]
    if metrics["wrapper_rules"]:
        lines.extend(f"- `{rule}`: {count}" for rule, count in metrics["wrapper_rules"].items())
    else:
        lines.append("- No wrapper rules fired.")
    lines.extend(["", "## Field Deltas", ""])
    if metrics["repair_counts"]:
        lines.extend(f"- `{key}`: {count}" for key, count in metrics["repair_counts"].items())
    else:
        lines.append("- No field deltas.")
    lines.extend(["", "## By Tool", ""])
    lines.append("| Tool | Rows | Raw next | Wrapped next | Raw executor | Wrapped executor |")
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: |")
    for tool, item in metrics["by_tool"].items():
        raw_item = item["raw"]
        wrapped_item = item["wrapped"]
        lines.append(
            f"| {tool} | {raw_item['rows']} | {percent(raw_item['next_action_accuracy'])} | "
            f"{percent(wrapped_item['next_action_accuracy'])} | {percent(raw_item['executor_kind_accuracy'])} | "
            f"{percent(wrapped_item['executor_kind_accuracy'])} |"
        )
    return "\n".join(lines) + "\n"


def metric_row(label: str, item: dict[str, Any]) -> str:
    return (
        f"| {label} | {percent(item['schema_valid_rate'])} | {percent(item['model_tier_accuracy'])} | "
        f"{percent(item['next_action_accuracy'])} | {percent(item['context_policy_accuracy'])} | "
        f"{percent(item['executor_kind_accuracy'])} |"
    )


def rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def percent(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2%}"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    main()
