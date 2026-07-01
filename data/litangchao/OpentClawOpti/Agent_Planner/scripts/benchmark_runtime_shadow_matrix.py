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

from architecture_policy import (  # noqa: E402
    POLICY_FIELDS,
    canonical_tool_name,
    permission_mode_for_row,
    policy_context_for_row,
    policy_from_tool_context,
    score_compact_policy,
    wrap_generation_row,
)
from evaluate_architecture_policy import (  # noqa: E402
    IM_END,
    iter_jsonl,
    load_references,
    normalize_policy_json,
    parse_assistant_json,
    policy_predictions,
    reference_key,
    strip_im_end,
)


DEFAULT_RAW = (
    AGENT_PLANNER_ROOT
    / "eval_runs"
    / "20260701T_architecture_policy_model_stage14_r2_1k"
    / "generations.jsonl"
)
DEFAULT_REFERENCE = (
    AGENT_PLANNER_ROOT
    / "eval_runs"
    / "20260701T_architecture_policy_model_stage14_r2_1k"
    / "eval_samples.jsonl"
)
DEFAULT_OUTPUT_DIR = AGENT_PLANNER_ROOT / "eval_runs" / "runtime_shadow_matrix"
PREDICTOR_KEYS = ("raw", "wrapped", "classifier", "classifier_no_next_prior")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Build an architecture-policy runtime shadow matrix that compares raw learned "
            "generations, serving wrapper output, a zero-generation enum classifier, and "
            "a no-next-prior counterfactual without changing the runtime planner."
        ),
    )
    parser.add_argument("--raw-generations", type=Path, default=DEFAULT_RAW)
    parser.add_argument("--reference", type=Path, default=DEFAULT_REFERENCE)
    parser.add_argument("--eval-samples", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--key-field", default="line_number")
    parser.add_argument("--max-rows", type=int, default=0)
    args = parser.parse_args()

    metrics = build_shadow_matrix(
        raw_generations=args.raw_generations,
        reference=args.reference,
        output_dir=args.output_dir,
        eval_samples=args.eval_samples,
        key_field=args.key_field,
        max_rows=args.max_rows,
    )
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


def build_shadow_matrix(
    *,
    raw_generations: Path,
    reference: Path,
    output_dir: Path,
    eval_samples: Path | None = None,
    key_field: str = "line_number",
    max_rows: int = 0,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    rows_path = output_dir / "shadow_matrix_rows.jsonl"
    references = load_references(reference, key_field=key_field)
    samples = load_references(eval_samples, key_field=key_field) if eval_samples else references

    aggregates = {key: new_aggregate() for key in PREDICTOR_KEYS}
    by_tool = {key: {} for key in PREDICTOR_KEYS}
    by_permission = {key: {} for key in PREDICTOR_KEYS}
    wrapper_rules: Counter[str] = Counter()
    raw_to_wrapped_delta: Counter[str] = Counter()
    no_next_to_classifier_delta: Counter[str] = Counter()
    examples: list[dict[str, Any]] = []
    rows_seen = 0
    rows_written = 0

    with raw_generations.open(encoding="utf-8") as input_handle, rows_path.open("w", encoding="utf-8") as output_handle:
        for raw_line_number, line in enumerate(input_handle, start=1):
            if max_rows and rows_written >= max_rows:
                break
            if not line.strip():
                continue
            rows_seen += 1
            raw_row = json.loads(line)
            key = reference_key(raw_row, raw_line_number, key_field)
            reference_row = references.get(key)
            if reference_row is None:
                continue
            sample_row = samples.get(key)
            merged = merge_context(raw_row, sample_row)
            expected = expected_policy(reference_row)
            permission_mode = permission_mode_for_row(merged)
            context = policy_context_for_row(merged)
            task_id = context.get("task_id") or "unknown"
            tool_name = canonical_tool_name(context.get("tool_name") or raw_row_tool(raw_row) or "planner")
            action = context.get("action") or ""

            raw_policy = extract_raw_policy(raw_row)
            wrapped_row, rules = wrap_generation_row(merged)
            wrapped_policy = compact_policy_from_wrapped(wrapped_row)
            classifier_policy, classifier_rules = policy_from_tool_context(
                tool_name=tool_name,
                permission_mode=permission_mode,
                task_id=task_id,
                action=action,
                apply_next_action_priors=True,
            )
            no_next_policy, no_next_rules = policy_from_tool_context(
                tool_name=tool_name,
                permission_mode=permission_mode,
                task_id=task_id,
                action=action,
                apply_next_action_priors=False,
            )

            predictions = {
                "raw": raw_policy,
                "wrapped": wrapped_policy,
                "classifier": classifier_policy,
                "classifier_no_next_prior": no_next_policy,
            }
            scores = {
                name: score_compact_policy(policy, expected)
                for name, policy in predictions.items()
            }
            for name in PREDICTOR_KEYS:
                update_aggregate(aggregates[name], scores[name])
                update_group(by_tool[name], tool_name, scores[name])
                update_group(by_permission[name], permission_mode or "UNKNOWN", scores[name])
            for rule in rules:
                wrapper_rules[rule] += 1
            for field, delta in compare_field_delta(scores["raw"], scores["wrapped"]).items():
                raw_to_wrapped_delta[f"{field}:{delta}"] += 1
            for field, delta in compare_field_delta(scores["classifier_no_next_prior"], scores["classifier"]).items():
                no_next_to_classifier_delta[f"{field}:{delta}"] += 1

            matrix_row = {
                "line_number": raw_line_number,
                "key": key,
                "transition_id": raw_row.get("transition_id") or reference_row.get("transition_id"),
                "task_id": task_id,
                "tool_name": tool_name,
                "permission_mode": permission_mode,
                "expected": expected,
                "predictions": predictions,
                "matches": {name: scores[name]["matches"] for name in PREDICTOR_KEYS},
                "exact_match": {name: scores[name]["exact_match"] for name in PREDICTOR_KEYS},
                "would_change_runtime": {
                    name: not scores[name]["exact_match"]
                    for name in PREDICTOR_KEYS
                },
                "wrapper_rules": rules,
                "classifier_rules": classifier_rules,
                "classifier_no_next_prior_rules": no_next_rules,
            }
            if should_keep_example(matrix_row, examples):
                examples.append(matrix_row)
            output_handle.write(json.dumps(matrix_row, ensure_ascii=False, separators=(",", ":")) + "\n")
            rows_written += 1

    metrics = {
        "created_at": utc_now(),
        "raw_generations": str(raw_generations),
        "reference": str(reference),
        "eval_samples": str(eval_samples) if eval_samples else str(reference),
        "key_field": key_field,
        "rows_seen": rows_seen,
        "rows_written": rows_written,
        "rows_jsonl": str(rows_path),
        "predictors": {key: finalize_aggregate(aggregates[key]) for key in PREDICTOR_KEYS},
        "by_tool": {key: finalize_groups(by_tool[key]) for key in PREDICTOR_KEYS},
        "by_permission_mode": {key: finalize_groups(by_permission[key]) for key in PREDICTOR_KEYS},
        "wrapper_rule_counts": dict(sorted(wrapper_rules.items())),
        "raw_to_wrapped_delta": dict(sorted(raw_to_wrapped_delta.items())),
        "no_next_prior_to_classifier_delta": dict(sorted(no_next_to_classifier_delta.items())),
        "example_rows": examples[:40],
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


def expected_policy(row: dict[str, Any]) -> dict[str, str]:
    expected = row.get("expected") if isinstance(row.get("expected"), dict) else {}
    target = row.get("compact_target") if isinstance(row.get("compact_target"), dict) else {}
    if not target:
        target = parse_target(row)
    return {
        "model_tier": str(expected.get("model_tier") or target.get("model_tier") or "unknown"),
        "verifier_next_action": str(expected.get("next_action") or target.get("verifier_next_action") or "unknown"),
        "context_policy": str(expected.get("context_policy") or target.get("context_policy") or "unknown"),
        "executor_kind": str(expected.get("executor_kind") or target.get("executor_kind") or "unknown"),
    }


def parse_target(row: dict[str, Any]) -> dict[str, Any]:
    for key in ("target", "text"):
        value = row.get(key)
        if not isinstance(value, str):
            continue
        cleaned = strip_im_end(value).strip()
        start = cleaned.rfind("{")
        end = cleaned.rfind("}")
        if start < 0 or end < start:
            continue
        try:
            parsed = json.loads(cleaned[start:end + 1])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return {}


def extract_raw_policy(row: dict[str, Any]) -> dict[str, str]:
    text = row.get("generated_text") or row.get("prediction") or row.get("assistant")
    parsed = parse_assistant_json(strip_im_end(text)) if isinstance(text, str) else None
    normalized, _ = normalize_policy_json(parsed)
    predictions = policy_predictions(normalized)
    architecture = normalized.get("architecture") if isinstance(normalized, dict) else {}
    task_id = architecture.get("task_id") if isinstance(architecture, dict) else None
    tool_name = architecture.get("tool_name") if isinstance(architecture, dict) else None
    return {
        "task_id": task_id if isinstance(task_id, str) else "unknown",
        "tool_name": canonical_tool_name(tool_name) if isinstance(tool_name, str) else "unknown",
        "model_tier": predictions.get("model_tier") or "unknown",
        "verifier_next_action": predictions.get("next_action") or "unknown",
        "context_policy": predictions.get("context_policy") or "unknown",
        "executor_kind": predictions.get("executor_kind") or "unknown",
    }


def raw_row_tool(row: dict[str, Any]) -> str:
    policy = extract_raw_policy(row)
    return policy.get("tool_name") or ""


def compact_policy_from_wrapped(row: dict[str, Any]) -> dict[str, str]:
    policy = row.get("architecture_policy") if isinstance(row.get("architecture_policy"), dict) else {}
    return {
        "task_id": str(policy.get("task_id") or "unknown"),
        "tool_name": canonical_tool_name(str(policy.get("tool_name") or "unknown")),
        "model_tier": str(policy.get("model_tier") or "unknown"),
        "verifier_next_action": str(policy.get("verifier_next_action") or "unknown"),
        "context_policy": str(policy.get("context_policy") or "unknown"),
        "executor_kind": str(policy.get("executor_kind") or "unknown"),
    }


def compare_field_delta(
    before: dict[str, Any],
    after: dict[str, Any],
) -> dict[str, str]:
    output: dict[str, str] = {}
    for field in POLICY_FIELDS:
        before_ok = bool(before["matches"].get(field))
        after_ok = bool(after["matches"].get(field))
        if before_ok and after_ok:
            output[field] = "unchanged_correct"
        elif not before_ok and after_ok:
            output[field] = "repaired"
        elif before_ok and not after_ok:
            output[field] = "regressed"
        else:
            output[field] = "unchanged_wrong"
    return output


def should_keep_example(row: dict[str, Any], examples: list[dict[str, Any]]) -> bool:
    if len(examples) >= 40:
        return False
    exact = row["exact_match"]
    if not exact["raw"] or not exact["classifier_no_next_prior"]:
        return True
    return bool(row["wrapper_rules"])


def new_aggregate() -> Counter[str]:
    return Counter()


def update_aggregate(counter: Counter[str], score: dict[str, Any]) -> None:
    counter["rows"] += 1
    if score["exact_match"]:
        counter["exact_matches"] += 1
    for field, matched in score["matches"].items():
        counter[f"{field}_total"] += 1
        if matched:
            counter[f"{field}_correct"] += 1


def update_group(groups: dict[str, Counter[str]], key: str, score: dict[str, Any]) -> None:
    group = groups.setdefault(key or "__missing__", Counter())
    update_aggregate(group, score)


def finalize_aggregate(counter: Counter[str]) -> dict[str, Any]:
    rows = counter["rows"]
    output: dict[str, Any] = {
        "rows": rows,
        "exact_matches": counter["exact_matches"],
        "exact_match_rate": rate(counter["exact_matches"], rows),
        "would_change_runtime_rate": rate(rows - counter["exact_matches"], rows),
    }
    for field in POLICY_FIELDS:
        total = counter[f"{field}_total"]
        correct = counter[f"{field}_correct"]
        output[f"{field}_accuracy"] = rate(correct, total)
        output[f"{field}_correct"] = correct
        output[f"{field}_total"] = total
    return output


def finalize_groups(groups: dict[str, Counter[str]]) -> dict[str, Any]:
    return {key: finalize_aggregate(counter) for key, counter in sorted(groups.items())}


def rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def render_report(metrics: dict[str, Any]) -> str:
    lines = [
        "# Runtime Shadow Matrix",
        "",
        f"- raw_generations: `{metrics['raw_generations']}`",
        f"- reference: `{metrics['reference']}`",
        f"- rows_written: {metrics['rows_written']}",
        "",
        "## Predictor Summary",
        "",
        "| predictor | exact | would_change | model | next | context | executor |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for key in PREDICTOR_KEYS:
        item = metrics["predictors"][key]
        lines.append(
            "| {key} | {exact:.2%} | {change:.2%} | {model:.2%} | {next_action:.2%} | {context:.2%} | {executor:.2%} |".format(
                key=key,
                exact=item["exact_match_rate"],
                change=item["would_change_runtime_rate"],
                model=item["model_tier_accuracy"],
                next_action=item["verifier_next_action_accuracy"],
                context=item["context_policy_accuracy"],
                executor=item["executor_kind_accuracy"],
            )
        )
    lines.extend([
        "",
        "## Wrapper Rules",
        "",
    ])
    if metrics["wrapper_rule_counts"]:
        for rule, count in metrics["wrapper_rule_counts"].items():
            lines.append(f"- `{rule}`: {count}")
    else:
        lines.append("- none")
    lines.extend([
        "",
        "## Raw To Wrapped Delta",
        "",
    ])
    for key, count in metrics["raw_to_wrapped_delta"].items():
        lines.append(f"- `{key}`: {count}")
    lines.extend([
        "",
        "## No-Next-Prior Counterfactual Delta",
        "",
    ])
    for key, count in metrics["no_next_prior_to_classifier_delta"].items():
        lines.append(f"- `{key}`: {count}")
    lines.append("")
    return "\n".join(lines)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    main()
