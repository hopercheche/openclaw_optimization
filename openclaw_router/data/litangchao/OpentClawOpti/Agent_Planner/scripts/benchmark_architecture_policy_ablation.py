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


DEFAULT_INPUT = (
    AGENT_PLANNER_ROOT
    / "processed"
    / "stage16_architecture_policy_unsolvable_toolhazard_perturbations_1k.jsonl"
)
DEFAULT_OUTPUT_DIR = AGENT_PLANNER_ROOT / "eval_runs" / "architecture_policy_ablation"
ABLATIONS: dict[str, dict[str, bool]] = {
    "full": {
        "apply_tool_priors": True,
        "apply_next_action_priors": True,
        "apply_permission_guards": True,
        "apply_hazard_guards": True,
    },
    "no_next_action_prior": {
        "apply_tool_priors": True,
        "apply_next_action_priors": False,
        "apply_permission_guards": True,
        "apply_hazard_guards": True,
    },
    "no_tool_priors": {
        "apply_tool_priors": False,
        "apply_next_action_priors": False,
        "apply_permission_guards": True,
        "apply_hazard_guards": True,
    },
    "no_permission_guards": {
        "apply_tool_priors": True,
        "apply_next_action_priors": True,
        "apply_permission_guards": False,
        "apply_hazard_guards": True,
    },
    "no_hazard_guards": {
        "apply_tool_priors": True,
        "apply_next_action_priors": True,
        "apply_permission_guards": True,
        "apply_hazard_guards": False,
    },
    "tool_priors_only": {
        "apply_tool_priors": True,
        "apply_next_action_priors": True,
        "apply_permission_guards": False,
        "apply_hazard_guards": False,
    },
}


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Run fine-grained ablations for the zero-generation architecture-policy classifier "
            "to measure which priors/guards are still required."
        ),
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--max-rows", type=int, default=0)
    args = parser.parse_args()

    metrics = evaluate_ablation(input_path=args.input, output_dir=args.output_dir, max_rows=args.max_rows)
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


def evaluate_ablation(*, input_path: Path, output_dir: Path, max_rows: int = 0) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    predictions_path = output_dir / "ablation_predictions.jsonl"
    aggregates = {name: new_aggregate() for name in ABLATIONS}
    by_type = {name: {} for name in ABLATIONS}
    by_expected_next = {name: {} for name in ABLATIONS}
    rule_counts = {name: Counter() for name in ABLATIONS}
    examples: list[dict[str, Any]] = []
    stats: Counter[str] = Counter()
    elapsed = Counter()

    with input_path.open(encoding="utf-8") as input_handle, predictions_path.open("w", encoding="utf-8") as output_handle:
        for line_number, line in enumerate(input_handle, start=1):
            if max_rows and stats["rows"] >= max_rows:
                break
            if not line.strip():
                continue
            row = json.loads(line)
            prompt = prompt_from_row(row)
            if prompt is None:
                stats["rows_skipped"] += 1
                continue
            classifier_row = {
                "prompt": prompt,
                "task_preview": row.get("task_preview") if isinstance(row.get("task_preview"), str) else "",
                "permission_mode": row.get("permission_mode") if isinstance(row.get("permission_mode"), str) else "",
            }
            context = policy_context_for_row(classifier_row)
            expected = expected_policy(row)
            record = {
                "line_number": line_number,
                "transition_id": row.get("transition_id"),
                "perturbation_type": perturbation_type(row),
                "expected_next_action": expected["verifier_next_action"],
                "permission_mode": permission_mode_for_row(classifier_row),
                "expected": expected,
                "predictions": {},
                "matches": {},
                "exact_match": {},
                "rules": {},
            }
            for name, flags in ABLATIONS.items():
                started = time.perf_counter()
                prediction, rules = policy_from_tool_context(
                    tool_name=context.get("tool_name") or "planner",
                    permission_mode=permission_mode_for_row(classifier_row),
                    task_id=context.get("task_id") or "unknown",
                    action=context.get("action") or "",
                    **flags,
                )
                elapsed[name] += time.perf_counter() - started
                score = score_compact_policy(prediction, expected)
                update_aggregate(aggregates[name], score)
                update_group(by_type[name], record["perturbation_type"], score)
                update_group(by_expected_next[name], expected["verifier_next_action"], score)
                for rule in rules:
                    rule_counts[name][rule] += 1
                record["predictions"][name] = prediction
                record["matches"][name] = score["matches"]
                record["exact_match"][name] = score["exact_match"]
                record["rules"][name] = rules
            if should_keep_example(record, examples):
                examples.append(record)
            output_handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
            stats["rows"] += 1

    metrics = {
        "created_at": utc_now(),
        "input": str(input_path),
        "output_dir": str(output_dir),
        "predictions_jsonl": str(predictions_path),
        "rows": stats["rows"],
        "rows_skipped": stats["rows_skipped"],
        "ablations": {
            name: finalize_aggregate(aggregates[name], elapsed_seconds=elapsed[name])
            for name in ABLATIONS
        },
        "by_perturbation_type": {
            name: finalize_groups(by_type[name])
            for name in ABLATIONS
        },
        "by_expected_next_action": {
            name: finalize_groups(by_expected_next[name])
            for name in ABLATIONS
        },
        "rule_counts": {
            name: dict(sorted(counter.items()))
            for name, counter in sorted(rule_counts.items())
        },
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


def prompt_from_row(row: dict[str, Any]) -> str | None:
    prompt = row.get("prompt")
    if isinstance(prompt, str) and prompt:
        return prompt
    text = row.get("text")
    if not isinstance(text, str):
        return None
    split = split_sft_text(text)
    return split[0] if split else None


def expected_policy(row: dict[str, Any]) -> dict[str, str]:
    expected = row.get("expected") if isinstance(row.get("expected"), dict) else {}
    return {
        "model_tier": str(expected.get("model_tier") or row.get("expected_model_tier") or "unknown"),
        "verifier_next_action": str(
            expected.get("next_action")
            or expected.get("verifier_next_action")
            or row.get("expected_next_action")
            or "unknown"
        ),
        "context_policy": str(expected.get("context_policy") or "unknown"),
        "executor_kind": str(expected.get("executor_kind") or "unknown"),
    }


def perturbation_type(row: dict[str, Any]) -> str:
    value = row.get("perturbation_type")
    if isinstance(value, str) and value:
        return value
    perturbation = row.get("perturbation")
    if isinstance(perturbation, dict) and isinstance(perturbation.get("type"), str):
        return perturbation["type"]
    return "clean"


def should_keep_example(row: dict[str, Any], examples: list[dict[str, Any]]) -> bool:
    if len(examples) >= 40:
        return False
    if row["exact_match"].get("full") is False:
        return True
    return any(not matched for name, matched in row["exact_match"].items() if name != "full")


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


def finalize_aggregate(counter: Counter[str], *, elapsed_seconds: float = 0.0) -> dict[str, Any]:
    rows = counter["rows"]
    output: dict[str, Any] = {
        "rows": rows,
        "exact_matches": counter["exact_matches"],
        "exact_match_rate": rate(counter["exact_matches"], rows),
        "would_change_runtime_rate": rate(rows - counter["exact_matches"], rows),
        "total_prediction_seconds": round(elapsed_seconds, 6),
        "mean_prediction_seconds": round(elapsed_seconds / rows, 8) if rows else 0.0,
    }
    for field in POLICY_FIELDS:
        total = counter[f"{field}_total"]
        correct = counter[f"{field}_correct"]
        output[f"{field}_accuracy"] = rate(correct, total)
        output[f"{field}_correct"] = correct
        output[f"{field}_total"] = total
    return output


def finalize_groups(groups: dict[str, Counter[str]]) -> dict[str, Any]:
    return {
        key: finalize_aggregate(counter)
        for key, counter in sorted(groups.items())
    }


def rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 6) if denominator else 0.0


def render_report(metrics: dict[str, Any]) -> str:
    lines = [
        "# Architecture Policy Ablation",
        "",
        f"- input: `{metrics['input']}`",
        f"- rows: {metrics['rows']}",
        "",
        "## Ablations",
        "",
        "| Variant | Exact | Model | Next | Context | Executor | Mean seconds |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name, item in metrics["ablations"].items():
        lines.append(
            "| "
            f"{name} | "
            f"{pct(item['exact_match_rate'])} | "
            f"{pct(item['model_tier_accuracy'])} | "
            f"{pct(item['verifier_next_action_accuracy'])} | "
            f"{pct(item['context_policy_accuracy'])} | "
            f"{pct(item['executor_kind_accuracy'])} | "
            f"{item['mean_prediction_seconds']:.8f} |"
        )
    lines.extend(["", "## Interpretation", ""])
    lines.append(
        "Exact-rate drops identify priors/guards that are still carrying behavior "
        "and should be distilled before being removed."
    )
    return "\n".join(lines) + "\n"


def pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    main()
