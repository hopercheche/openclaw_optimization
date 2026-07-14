#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


AGENT_PLANNER_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TARGET_EVAL = (
    AGENT_PLANNER_ROOT
    / "eval_runs"
    / "20260701T_stage17_architecture_adapter_sft_toolmaze_1k_target_eval"
)
DEFAULT_CLASSIFIER_EVAL = (
    AGENT_PLANNER_ROOT
    / "eval_runs"
    / "20260701T_stage17_enum_classifier_adapter_toolmaze_1k_layers"
)
DEFAULT_HARD_NEGATIVE_EVAL = (
    AGENT_PLANNER_ROOT
    / "eval_runs"
    / "20260701T_stage17_enum_classifier_toolmaze_5216_layers"
)
DEFAULT_ABLATION_EVAL = (
    AGENT_PLANNER_ROOT
    / "eval_runs"
    / "20260701T_stage17_architecture_policy_ablation_toolmaze_5216"
)
DEFAULT_ADAPTER_SUMMARY = (
    AGENT_PLANNER_ROOT
    / "processed"
    / "stage17_architecture_policy_adapter_sft_toolmaze_1k.jsonl.summary.json"
)
DEFAULT_RUNTIME_SHADOW_EVAL = (
    AGENT_PLANNER_ROOT
    / "eval_runs"
    / "20260701T_architecture_policy_shadow_full_r1"
)
DEFAULT_OUTPUT_DIR = AGENT_PLANNER_ROOT / "eval_runs" / "architecture_policy_promotion_gate"


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Check whether an OpenClaw architecture-policy candidate is ready for "
            "adapter training, runtime shadowing, or learned replacement."
        ),
    )
    parser.add_argument("--target-eval", type=Path, default=DEFAULT_TARGET_EVAL)
    parser.add_argument("--classifier-eval", type=Path, default=DEFAULT_CLASSIFIER_EVAL)
    parser.add_argument("--hard-negative-eval", type=Path, default=DEFAULT_HARD_NEGATIVE_EVAL)
    parser.add_argument("--ablation-eval", type=Path, default=DEFAULT_ABLATION_EVAL)
    parser.add_argument("--adapter-summary", type=Path, default=DEFAULT_ADAPTER_SUMMARY)
    parser.add_argument("--runtime-shadow-eval", type=Path, default=DEFAULT_RUNTIME_SHADOW_EVAL)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--min-target-rows", type=int, default=1000)
    parser.add_argument("--min-classifier-rows", type=int, default=1000)
    parser.add_argument("--min-hard-negative-rows", type=int, default=1000)
    parser.add_argument("--min-runtime-shadow-rows", type=int, default=500)
    parser.add_argument("--min-adapter-rows", type=int, default=1000)
    parser.add_argument("--min-exact-rate", type=float, default=1.0)
    parser.add_argument("--min-learned-ablation-rate", type=float, default=0.95)
    parser.add_argument("--max-classifier-mean-seconds", type=float, default=0.001)
    parser.add_argument("--min-next-action-fraction", type=float, default=0.2)
    args = parser.parse_args()

    report = check_promotion(
        target_eval=args.target_eval,
        classifier_eval=args.classifier_eval,
        hard_negative_eval=args.hard_negative_eval,
        ablation_eval=args.ablation_eval,
        adapter_summary=args.adapter_summary,
        runtime_shadow_eval=args.runtime_shadow_eval,
        output_dir=args.output_dir,
        min_target_rows=args.min_target_rows,
        min_classifier_rows=args.min_classifier_rows,
        min_hard_negative_rows=args.min_hard_negative_rows,
        min_runtime_shadow_rows=args.min_runtime_shadow_rows,
        min_adapter_rows=args.min_adapter_rows,
        min_exact_rate=args.min_exact_rate,
        min_learned_ablation_rate=args.min_learned_ablation_rate,
        max_classifier_mean_seconds=args.max_classifier_mean_seconds,
        min_next_action_fraction=args.min_next_action_fraction,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


def check_promotion(
    *,
    target_eval: Path,
    classifier_eval: Path,
    hard_negative_eval: Path,
    ablation_eval: Path,
    adapter_summary: Path,
    runtime_shadow_eval: Path | None,
    output_dir: Path,
    min_target_rows: int = 1000,
    min_classifier_rows: int = 1000,
    min_hard_negative_rows: int = 1000,
    min_runtime_shadow_rows: int = 500,
    min_adapter_rows: int = 1000,
    min_exact_rate: float = 1.0,
    min_learned_ablation_rate: float = 0.95,
    max_classifier_mean_seconds: float = 0.001,
    min_next_action_fraction: float = 0.2,
) -> dict[str, Any]:
    target_metrics = load_metrics(target_eval)
    classifier_metrics = load_metrics(classifier_eval)
    hard_negative_metrics = load_metrics(hard_negative_eval)
    ablation_metrics = load_metrics(ablation_eval)
    adapter_metrics = load_metrics(adapter_summary)
    runtime_shadow_metrics = load_metrics(runtime_shadow_eval) if runtime_shadow_eval is not None else None

    checks = {
        "target_eval": check_target_eval(
            target_metrics,
            source=target_eval,
            min_rows=min_target_rows,
            min_exact_rate=min_exact_rate,
        ),
        "classifier_eval": check_classifier_eval(
            classifier_metrics,
            source=classifier_eval,
            min_rows=min_classifier_rows,
            min_exact_rate=min_exact_rate,
            max_mean_seconds=max_classifier_mean_seconds,
        ),
        "hard_negative_eval": check_classifier_eval(
            hard_negative_metrics,
            source=hard_negative_eval,
            min_rows=min_hard_negative_rows,
            min_exact_rate=min_exact_rate,
            max_mean_seconds=max_classifier_mean_seconds,
        ),
        "adapter_summary": check_adapter_summary(
            adapter_metrics,
            source=adapter_summary,
            min_rows=min_adapter_rows,
            min_next_action_fraction=min_next_action_fraction,
        ),
        "ablation_eval": check_ablation_eval(
            ablation_metrics,
            source=ablation_eval,
            min_exact_rate=min_exact_rate,
            min_learned_ablation_rate=min_learned_ablation_rate,
        ),
    }
    if runtime_shadow_metrics is not None:
        checks["runtime_shadow_eval"] = check_classifier_eval(
            runtime_shadow_metrics,
            source=runtime_shadow_eval or Path(""),
            min_rows=min_runtime_shadow_rows,
            min_exact_rate=min_exact_rate,
            max_mean_seconds=None,
        )

    gates = build_gates(checks)
    report = {
        "created_at": utc_now(),
        "thresholds": {
            "min_target_rows": min_target_rows,
            "min_classifier_rows": min_classifier_rows,
            "min_hard_negative_rows": min_hard_negative_rows,
            "min_runtime_shadow_rows": min_runtime_shadow_rows,
            "min_adapter_rows": min_adapter_rows,
            "min_exact_rate": min_exact_rate,
            "min_learned_ablation_rate": min_learned_ablation_rate,
            "max_classifier_mean_seconds": max_classifier_mean_seconds,
            "min_next_action_fraction": min_next_action_fraction,
        },
        "checks": checks,
        "gates": gates,
        "recommendation": recommend(gates),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    metrics_path = output_dir / "promotion_report.json"
    report_path = output_dir / "promotion_report.md"
    metrics_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report_path.write_text(render_markdown(report), encoding="utf-8")
    report["outputs"] = {
        "promotion_report_json": str(metrics_path),
        "promotion_report_md": str(report_path),
    }
    return report


def check_target_eval(data: dict[str, Any], *, source: Path, min_rows: int, min_exact_rate: float) -> dict[str, Any]:
    overall = overall_metrics(data)
    requirements = {
        "rows": at_least(first_int(overall, ("rows",)), min_rows),
        "schema_valid_rate": at_least(first_float(overall, ("schema_valid_rate",)), min_exact_rate),
        "architecture_valid_rate": at_least(first_float(overall, ("architecture_valid_rate",)), min_exact_rate),
        "verifier_valid_rate": at_least(first_float(overall, ("verifier_valid_rate",)), min_exact_rate),
        "model_tier_accuracy": at_least(first_float(overall, ("model_tier_accuracy",)), min_exact_rate),
        "next_action_accuracy": at_least(
            first_float(overall, ("next_action_accuracy", "verifier_next_action_accuracy")),
            min_exact_rate,
        ),
        "context_policy_accuracy": at_least(first_float(overall, ("context_policy_accuracy",)), min_exact_rate),
        "executor_kind_accuracy": at_least(first_float(overall, ("executor_kind_accuracy",)), min_exact_rate),
    }
    return section_result(source=source, summary=selected_values(overall), requirements=requirements)


def check_classifier_eval(
    data: dict[str, Any],
    *,
    source: Path,
    min_rows: int,
    min_exact_rate: float,
    max_mean_seconds: float | None,
) -> dict[str, Any]:
    overall = overall_metrics(data)
    requirements = {
        "rows": at_least(first_int(overall, ("rows",)), min_rows),
        "exact_match_rate": at_least(first_float(overall, ("exact_match_rate",)), min_exact_rate),
        "model_tier_accuracy": at_least(first_float(overall, ("model_tier_accuracy",)), min_exact_rate),
        "next_action_accuracy": at_least(
            first_float(overall, ("verifier_next_action_accuracy", "next_action_accuracy")),
            min_exact_rate,
        ),
        "context_policy_accuracy": at_least(first_float(overall, ("context_policy_accuracy",)), min_exact_rate),
        "executor_kind_accuracy": at_least(first_float(overall, ("executor_kind_accuracy",)), min_exact_rate),
    }
    if "strategist_exact_rate" in overall:
        requirements["strategist_exact_rate"] = at_least(first_float(overall, ("strategist_exact_rate",)), min_exact_rate)
    if "architect_exact_rate" in overall:
        requirements["architect_exact_rate"] = at_least(first_float(overall, ("architect_exact_rate",)), min_exact_rate)
    if max_mean_seconds is not None:
        requirements["mean_prediction_seconds"] = at_most(
            first_float(overall, ("mean_prediction_seconds",)),
            max_mean_seconds,
        )
    return section_result(source=source, summary=selected_values(overall), requirements=requirements)


def check_adapter_summary(
    data: dict[str, Any],
    *,
    source: Path,
    min_rows: int,
    min_next_action_fraction: float,
) -> dict[str, Any]:
    rows = first_int(data, ("rows_written", "rows"))
    source_mix = data.get("source_mix_counts") if isinstance(data.get("source_mix_counts"), dict) else {}
    perturbation_types = data.get("perturbation_type_counts") if isinstance(data.get("perturbation_type_counts"), dict) else {}
    next_actions = data.get("expected_next_action_counts") if isinstance(data.get("expected_next_action_counts"), dict) else {}
    min_next_count = int((rows or 0) * min_next_action_fraction)
    requirements = {
        "rows_written": at_least(rows, min_rows),
        "has_rule_distillation": at_least(int(source_mix.get("rule_distillation", 0)), 1),
        "has_perturbations": at_least(int(source_mix.get("perturbation", 0)), 1),
        "perturbation_type_count": at_least(len(perturbation_types), 8),
        "await_human_min_fraction": at_least(int(next_actions.get("await_human", 0)), min_next_count),
        "next_subtask_min_fraction": at_least(int(next_actions.get("next_subtask", 0)), min_next_count),
        "replan_min_fraction": at_least(int(next_actions.get("replan", 0)), min_next_count),
    }
    summary = {
        "rows_written": rows,
        "source_mix_counts": source_mix,
        "perturbation_type_counts": perturbation_types,
        "expected_next_action_counts": next_actions,
    }
    return section_result(source=source, summary=summary, requirements=requirements)


def check_ablation_eval(
    data: dict[str, Any],
    *,
    source: Path,
    min_exact_rate: float,
    min_learned_ablation_rate: float,
) -> dict[str, Any]:
    ablations = data.get("ablations") if isinstance(data.get("ablations"), dict) else {}
    full_rate = ablation_rate(ablations, "full")
    no_tool_rate = ablation_rate(ablations, "no_tool_priors")
    no_next_rate = ablation_rate(ablations, "no_next_action_prior")
    no_permission_rate = ablation_rate(ablations, "no_permission_guards")
    no_hazard_rate = ablation_rate(ablations, "no_hazard_guards")
    requirements = {
        "full_exact_match_rate": at_least(full_rate, min_exact_rate),
        "no_tool_priors_learned_replacement": at_least(no_tool_rate, min_learned_ablation_rate),
        "no_next_action_prior_learned_replacement": at_least(no_next_rate, min_learned_ablation_rate),
        "no_permission_guards_learned_replacement": at_least(no_permission_rate, min_learned_ablation_rate),
        "no_hazard_guards_learned_replacement": at_least(no_hazard_rate, min_learned_ablation_rate),
    }
    summary = {
        "rows": first_int(data, ("rows",)),
        "full_exact_match_rate": full_rate,
        "no_tool_priors_exact_match_rate": no_tool_rate,
        "no_next_action_prior_exact_match_rate": no_next_rate,
        "no_permission_guards_exact_match_rate": no_permission_rate,
        "no_hazard_guards_exact_match_rate": no_hazard_rate,
        "rule_dependency_delta": {
            "tool_priors": delta(full_rate, no_tool_rate),
            "next_action_priors": delta(full_rate, no_next_rate),
            "permission_guards": delta(full_rate, no_permission_rate),
            "hazard_guards": delta(full_rate, no_hazard_rate),
        },
    }
    result = section_result(source=source, summary=summary, requirements=requirements)
    result["learned_replacement_ready"] = all(
        requirements[name]["passed"]
        for name in requirements
        if name != "full_exact_match_rate"
    )
    return result


def build_gates(checks: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    adapter_ready_inputs = ["target_eval", "adapter_summary"]
    runtime_inputs = ["classifier_eval", "hard_negative_eval", "runtime_shadow_eval"]
    learned_inputs = ["target_eval", "classifier_eval", "hard_negative_eval", "ablation_eval"]
    return {
        "adapter_train_ready": gate_from_sections(checks, adapter_ready_inputs),
        "runtime_shadow_ready": gate_from_sections(checks, runtime_inputs),
        "learned_replacement_ready": gate_from_sections(
            checks,
            learned_inputs,
            extra_pass=bool(checks.get("ablation_eval", {}).get("learned_replacement_ready")),
        ),
    }


def gate_from_sections(
    checks: dict[str, dict[str, Any]],
    section_names: list[str],
    *,
    extra_pass: bool = True,
) -> dict[str, Any]:
    missing = [name for name in section_names if name not in checks]
    failed = [name for name in section_names if name in checks and checks[name]["status"] != "pass"]
    if not extra_pass:
        failed.append("ablation_rule_dependency")
    status = "pass" if not missing and not failed else "fail"
    return {
        "status": status,
        "required_sections": section_names,
        "missing_sections": missing,
        "failed_sections": failed,
    }


def recommend(gates: dict[str, dict[str, Any]]) -> dict[str, str]:
    if gates["learned_replacement_ready"]["status"] == "pass":
        return {
            "level": "promote_learned_replacement",
            "message": "Candidate can be evaluated as a learned replacement for the rule-backed policy.",
        }
    if gates["runtime_shadow_ready"]["status"] == "pass":
        return {
            "level": "promote_runtime_shadow_only",
            "message": "Candidate is ready for runtime shadow or guarded wrapper use, but not learned replacement.",
        }
    if gates["adapter_train_ready"]["status"] == "pass":
        return {
            "level": "train_adapter_next",
            "message": "Data pack is ready for adapter training before runtime promotion.",
        }
    return {
        "level": "hold",
        "message": "Do not promote; fix failed checks first.",
    }


def section_result(*, source: Path, summary: dict[str, Any], requirements: dict[str, dict[str, Any]]) -> dict[str, Any]:
    failed = [name for name, requirement in requirements.items() if not requirement["passed"]]
    return {
        "source": str(source),
        "status": "pass" if not failed else "fail",
        "summary": summary,
        "requirements": requirements,
        "failed_requirements": failed,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Architecture Policy Promotion Gate",
        "",
        f"- created_at: `{report['created_at']}`",
        f"- recommendation: `{report['recommendation']['level']}`",
        f"- message: {report['recommendation']['message']}",
        "",
        "## Gates",
        "",
        "| gate | status | failed sections |",
        "| --- | --- | --- |",
    ]
    for name, gate in report["gates"].items():
        failed = ", ".join(gate["failed_sections"]) or "-"
        lines.append(f"| {name} | {gate['status']} | {failed} |")
    lines.extend(["", "## Checks", "", "| check | status | key summary | failed requirements |", "| --- | --- | --- | --- |"])
    for name, check in report["checks"].items():
        failed = ", ".join(check["failed_requirements"]) or "-"
        summary = compact_summary(check["summary"])
        lines.append(f"| {name} | {check['status']} | {summary} | {failed} |")
    lines.extend(["", "## Ablation Dependency", ""])
    ablation = report["checks"].get("ablation_eval", {}).get("summary", {})
    dependency = ablation.get("rule_dependency_delta") if isinstance(ablation, dict) else None
    if isinstance(dependency, dict):
        lines.extend(["| component | full-minus-ablated exact rate |", "| --- | ---: |"])
        for key, value in dependency.items():
            lines.append(f"| {key} | {format_number(value)} |")
    return "\n".join(lines) + "\n"


def compact_summary(summary: dict[str, Any]) -> str:
    keys = (
        "rows",
        "rows_written",
        "exact_match_rate",
        "schema_valid_rate",
        "next_action_accuracy",
        "verifier_next_action_accuracy",
        "mean_prediction_seconds",
        "full_exact_match_rate",
        "no_tool_priors_exact_match_rate",
    )
    parts = []
    for key in keys:
        if key in summary and summary[key] is not None:
            parts.append(f"{key}={format_number(summary[key])}")
    return ", ".join(parts) or "-"


def load_metrics(path: Path | None) -> dict[str, Any]:
    if path is None:
        raise ValueError("path is required")
    source = path
    if source.is_dir():
        for file_name in ("metrics.json", "summary.json", "promotion_report.json"):
            candidate = source / file_name
            if candidate.is_file():
                source = candidate
                break
    if not source.is_file():
        raise FileNotFoundError(source)
    data = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{source} must contain a JSON object.")
    return data


def overall_metrics(data: dict[str, Any]) -> dict[str, Any]:
    overall = data.get("overall")
    if isinstance(overall, dict):
        return overall
    return data


def selected_values(metrics: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "rows",
        "schema_valid_rate",
        "architecture_valid_rate",
        "verifier_valid_rate",
        "exact_match_rate",
        "mean_prediction_seconds",
        "model_tier_accuracy",
        "next_action_accuracy",
        "verifier_next_action_accuracy",
        "context_policy_accuracy",
        "executor_kind_accuracy",
        "strategist_exact_rate",
        "architect_exact_rate",
    )
    return {key: metrics.get(key) for key in keys if key in metrics}


def ablation_rate(ablations: dict[str, Any], name: str) -> float | None:
    section = ablations.get(name)
    if not isinstance(section, dict):
        return None
    return first_float(section, ("exact_match_rate",))


def at_least(value: int | float | None, threshold: int | float) -> dict[str, Any]:
    return {
        "value": value,
        "threshold": threshold,
        "operator": ">=",
        "passed": value is not None and value >= threshold,
    }


def at_most(value: int | float | None, threshold: int | float) -> dict[str, Any]:
    return {
        "value": value,
        "threshold": threshold,
        "operator": "<=",
        "passed": value is not None and value <= threshold,
    }


def first_int(mapping: dict[str, Any], keys: tuple[str, ...]) -> int | None:
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            return value
        if isinstance(value, float) and value.is_integer():
            return int(value)
    return None


def first_float(mapping: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            return float(value)
    return None


def delta(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    return round(left - right, 6)


def format_number(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    main()
