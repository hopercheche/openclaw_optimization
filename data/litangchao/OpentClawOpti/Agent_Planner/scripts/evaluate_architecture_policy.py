#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


AGENT_PLANNER_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = AGENT_PLANNER_ROOT / "processed" / "openclaw_architecture_balanced_holdout.jsonl"
DEFAULT_OUTPUT_DIR = AGENT_PLANNER_ROOT / "eval_runs" / "architecture_policy_eval"
ASSISTANT_MARKER = "<|im_start|>assistant\n"
IM_END = "<|im_end|>"
REQUIRED_TOP_FIELDS = ("analysis", "plan", "commands", "architecture", "verifier")
ARCHITECTURE_FIELDS = ("model_tier", "context_policy", "executor_kind", "expected_next_action")
POLICY_FIELDS = ("model_tier", "next_action", "context_policy", "executor_kind")
MISSING_GROUP = "__missing__"
NEXT_ACTION_ALIASES = {
    "await_human_or_next_goal": "next_subtask",
    "continue": "next_subtask",
    "execute": "next_subtask",
    "execute_plan": "next_subtask",
    "next": "next_subtask",
    "verify": "next_subtask",
    "verify_plan": "next_subtask",
    "verify_permission": "next_subtask",
    "human": "await_human",
    "ask": "await_human",
    "requires_human": "await_human",
    "block": "replan",
    "retry": "replan",
}
MODEL_TIER_ALIASES = {
    "low": "small",
    "fast": "small",
    "standard": "medium",
    "mid": "medium",
    "high": "large",
    "strong": "large",
}
CONTEXT_POLICY_ALIASES = {
    "execution_evidence+candidate_scores": "execution_evidence+critique_history",
    "permission_policy+risk_terms+candidate_history": "permission_policy+risk_terms",
    "permission_policy+safety_guidance": "permission_policy+risk_terms",
    "permission_policy+safety_terms": "permission_policy+risk_terms",
    "permission_policy+user_context": "permission_policy+risk_terms",
    "safety_policy+risk_terms": "permission_policy+risk_terms",
}
EXECUTOR_KIND_ALIASES = {
    "command_runner": "workspace_tool",
    "console": "workspace_tool",
    "console_tool": "workspace_tool",
    "file_writer": "workspace_tool",
    "goal_analyzer": "read_only_agent",
    "local_command": "workspace_tool",
    "mobile_agent": "external_tool",
    "mobile_app": "external_tool",
    "mobile_cli": "external_tool",
    "mobile_cli_runner": "external_tool",
    "mobile_gui": "external_tool",
    "mobile_gui_runner": "external_tool",
    "mobile_gui_tool": "external_tool",
    "mcp_tool": "external_tool",
    "mcp_tool_runner": "external_tool",
    "online_agent": "external_tool",
    "planner": "read_only_agent",
    "python_tool": "workspace_tool",
    "remote_agent": "external_tool",
    "remote_graph_node": "external_tool",
    "risk_model": "policy_gate",
    "permission_gate": "policy_gate",
    "permission_policy": "policy_gate",
    "permission_policy+verifier": "policy_gate",
    "policy_graph_policy": "policy_gate",
    "safety_guard": "policy_gate",
    "safety_wrapper": "policy_gate",
    "terminal_tool": "workspace_tool",
    "workspace_agent": "workspace_tool",
    "workspace_inspector": "read_only_agent",
}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate OpenClaw Agent_Planner architecture-policy SFT JSONL rows.",
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--metrics-json", type=Path, default=None)
    parser.add_argument("--report-md", type=Path, default=None)
    parser.add_argument("--max-rows", type=int, default=0)
    parser.add_argument(
        "--reference",
        type=Path,
        default=None,
        help="Optional SFT JSONL with labels keyed by --key-field, used to score generation rows.",
    )
    parser.add_argument("--key-field", default="line_number")
    parser.add_argument(
        "--normalize-compact",
        action="store_true",
        help="Normalize compact policy JSON into the full architecture schema before scoring.",
    )
    parser.add_argument("--fail-on-invalid", action="store_true")
    args = parser.parse_args()

    metrics = evaluate_file(
        args.input,
        max_rows=args.max_rows,
        reference_path=args.reference,
        key_field=args.key_field,
        normalize_compact=args.normalize_compact,
    )
    metrics_json = args.metrics_json or args.output_dir / "metrics.json"
    report_md = args.report_md or args.output_dir / "report.md"
    metrics["outputs"] = {
        "metrics_json": str(metrics_json),
        "report_md": str(report_md),
    }
    metrics_json.parent.mkdir(parents=True, exist_ok=True)
    report_md.parent.mkdir(parents=True, exist_ok=True)
    metrics_json.write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report_md.write_text(render_markdown(metrics), encoding="utf-8")
    print(json.dumps(metrics, ensure_ascii=False, indent=2))

    if args.fail_on_invalid and metrics["overall"]["schema_valid_count"] != metrics["overall"]["rows"]:
        raise SystemExit(1)


def evaluate_file(
    path: Path,
    *,
    max_rows: int = 0,
    reference_path: Path | None = None,
    key_field: str = "line_number",
    normalize_compact: bool = False,
) -> dict[str, Any]:
    references = load_references(reference_path, key_field=key_field) if reference_path else {}
    aggregate = new_aggregate()
    by_stratum: dict[str, dict[str, Any]] = {}
    by_source_mode: dict[str, dict[str, Any]] = {}
    by_model_label: dict[str, dict[str, Any]] = {}
    label_sources: dict[str, Counter[str]] = {field: Counter() for field in POLICY_FIELDS}
    parse_failures: list[dict[str, Any]] = []

    for line_number, row in iter_jsonl(path):
        if max_rows and aggregate["rows"] >= max_rows:
            break
        reference = references.get(reference_key(row, line_number, key_field))
        result = evaluate_row(
            row,
            line_number=line_number,
            reference=reference,
            normalize_compact=normalize_compact,
        )
        update_aggregate(aggregate, result)
        update_aggregate(by_stratum.setdefault(result["stratum"], new_aggregate()), result)
        update_aggregate(by_source_mode.setdefault(result["source_mode"], new_aggregate()), result)
        update_aggregate(by_model_label.setdefault(result["model_label"], new_aggregate()), result)
        for field, source in result["label_sources"].items():
            label_sources[field][source] += 1
        if result["parse_error"] and len(parse_failures) < 20:
            parse_failures.append({
                "line_number": line_number,
                "transition_id": row.get("transition_id"),
                "error": result["parse_error"],
            })

    return {
        "created_at": utc_now(),
        "input_file": str(path),
        "reference_file": str(reference_path) if reference_path else None,
        "max_rows": max_rows,
        "key_field": key_field,
        "normalize_compact": normalize_compact,
        "overall": finalize_aggregate(aggregate),
        "by_stratum": {
            key: finalize_aggregate(value)
            for key, value in sorted(by_stratum.items())
        },
        "by_source_mode": {
            key: finalize_aggregate(value)
            for key, value in sorted(by_source_mode.items())
        },
        "by_model_label": {
            key: finalize_aggregate(value)
            for key, value in sorted(by_model_label.items())
        },
        "label_sources": {
            field: dict(sorted(counter.items()))
            for field, counter in sorted(label_sources.items())
        },
        "parse_failures_sample": parse_failures,
    }


def evaluate_row(
    row: dict[str, Any],
    *,
    line_number: int,
    reference: dict[str, Any] | None = None,
    normalize_compact: bool = False,
) -> dict[str, Any]:
    assistant_text, text_error = assistant_text_from_row(row)
    parsed = parse_assistant_json(assistant_text) if assistant_text is not None else None
    raw_schema = score_schema(parsed)
    normalized = False
    if normalize_compact:
        parsed, normalized = normalize_policy_json(parsed)
    schema = score_schema(parsed)
    parse_error = None
    if assistant_text is None:
        parse_error = text_error or "missing_assistant_text"
    elif parsed is None:
        parse_error = "invalid_assistant_json"

    predictions = policy_predictions(parsed)
    expected, label_sources = expected_policy_labels(row, parsed, predictions, reference=reference)
    matches = {
        field: (
            predictions.get(field) == expected[field]
            if expected.get(field) is not None
            else None
        )
        for field in POLICY_FIELDS
    }
    source_mode = source_mode_for_row(row, expected, reference=reference)
    stratum = stratum_for_row(row, source_mode, expected, reference=reference)
    return {
        "line_number": line_number,
        "model_label": model_label_for_row(row),
        "raw_schema": raw_schema,
        "schema": schema,
        "normalized": normalized,
        "predictions": predictions,
        "expected": expected,
        "matches": matches,
        "label_sources": label_sources,
        "stratum": stratum,
        "source_mode": source_mode,
        "parse_error": parse_error,
    }


def assistant_text_from_row(row: dict[str, Any]) -> tuple[str | None, str | None]:
    text = row.get("text")
    if isinstance(text, str):
        marker_index = text.rfind(ASSISTANT_MARKER)
        if marker_index < 0:
            return text, None
        completion = text[marker_index + len(ASSISTANT_MARKER):]
        return strip_im_end(completion), None

    for key in ("assistant", "completion", "target", "generated_text", "prediction"):
        value = row.get(key)
        if isinstance(value, str):
            return strip_im_end(value), None

    messages = row.get("messages")
    if isinstance(messages, list):
        for message in reversed(messages):
            if not isinstance(message, dict):
                continue
            role = str(message.get("role") or "")
            content = message.get("content")
            if role == "assistant" and isinstance(content, str):
                return strip_im_end(content), None

    return None, "row_has_no_text_or_assistant_content"


def strip_im_end(text: str) -> str:
    stripped = text.strip()
    if stripped.endswith(IM_END):
        stripped = stripped[: -len(IM_END)].strip()
    return stripped


def parse_assistant_json(text: str) -> dict[str, Any] | None:
    cleaned = text.replace(IM_END, "")
    cleaned = re.sub(r"<think>.*?</think>", "", cleaned, flags=re.DOTALL)
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


def normalize_policy_json(parsed: dict[str, Any] | None) -> tuple[dict[str, Any] | None, bool]:
    if not isinstance(parsed, dict):
        return parsed, False
    if score_schema(parsed)["schema_valid"]:
        return parsed, False

    architecture = parsed.get("architecture") if isinstance(parsed.get("architecture"), dict) else {}
    verifier = parsed.get("verifier") if isinstance(parsed.get("verifier"), dict) else {}
    model_tier = canonical_model_tier(
        string_or_none(architecture.get("model_tier")) or string_or_none(parsed.get("model_tier"))
    )
    context_policy = (
        canonical_context_policy(
            string_or_none(architecture.get("context_policy"))
            or string_or_none(parsed.get("context_policy"))
        )
    )
    executor_kind = (
        canonical_executor_kind(
            string_or_none(architecture.get("executor_kind"))
            or string_or_none(parsed.get("executor_kind"))
        )
    )
    next_action = canonical_next_action(
        string_or_none(verifier.get("next_action"))
        or string_or_none(architecture.get("expected_next_action"))
        or string_or_none(parsed.get("next_action"))
        or string_or_none(parsed.get("verifier_next_action"))
    )
    if not any([model_tier, context_policy, executor_kind, next_action]):
        return parsed, False

    tool_name = string_or_none(architecture.get("tool_name")) or string_or_none(parsed.get("tool_name")) or "planner"
    normalized = {
        "analysis": string_or_none(parsed.get("analysis")) or "Normalized compact architecture policy output.",
        "plan": string_or_none(parsed.get("plan")) or (
            "Use the selected model tier, context policy, executor kind, and verifier next action."
        ),
        "commands": parsed.get("commands") if isinstance(parsed.get("commands"), list) and parsed["commands"] else [
            {
                "keystrokes": (
                    "openclaw.plan_subtask "
                    f"--tool {tool_name} "
                    f"--model-tier {model_tier or 'unknown'} "
                    f"--context-policy {context_policy or 'unknown'} "
                    f"--next-action {next_action or 'unknown'}"
                ),
                "duration": 1,
            }
        ],
        "task_complete": parsed.get("task_complete") if isinstance(parsed.get("task_complete"), bool) else False,
        "architecture": {
            **architecture,
            "task_id": string_or_none(architecture.get("task_id")) or string_or_none(parsed.get("task_id")) or "unknown",
            "tool_name": tool_name,
            "action": string_or_none(architecture.get("action")) or string_or_none(parsed.get("action")) or "",
            "model_tier": model_tier or "unknown",
            "risk_level": string_or_none(architecture.get("risk_level")) or string_or_none(parsed.get("risk_level")) or "unknown",
            "context_policy": context_policy or "unknown",
            "memory_queries": architecture.get("memory_queries") if isinstance(architecture.get("memory_queries"), list) else [],
            "success_criteria": (
                architecture.get("success_criteria")
                if isinstance(architecture.get("success_criteria"), list)
                else []
            ),
            "executor_kind": executor_kind or "unknown",
            "expected_next_action": next_action or "unknown",
        },
        "verifier": {
            **verifier,
            "next_action": next_action or "unknown",
        },
    }
    return normalized, True


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


def score_schema(parsed: dict[str, Any] | None) -> dict[str, Any]:
    if parsed is None:
        return {
            "valid_json": False,
            "schema_valid": False,
            "required_field_fraction": 0.0,
            "commands_valid": False,
            "architecture_valid": False,
            "verifier_valid": False,
        }

    commands = parsed.get("commands")
    commands_valid = isinstance(commands, list) and len(commands) > 0 and all(
        isinstance(command, dict)
        and isinstance(command.get("keystrokes"), str)
        and (
            "duration" not in command
            or isinstance(command.get("duration"), int | float)
        )
        for command in commands
    )
    architecture = parsed.get("architecture")
    architecture_valid = isinstance(architecture, dict) and all(
        isinstance(architecture.get(field), str)
        for field in ARCHITECTURE_FIELDS
    )
    verifier = parsed.get("verifier")
    verifier_valid = isinstance(verifier, dict) and isinstance(verifier.get("next_action"), str)
    fields_present = sum(1 for field in REQUIRED_TOP_FIELDS if field in parsed)
    schema_valid = (
        isinstance(parsed.get("analysis"), str)
        and isinstance(parsed.get("plan"), str)
        and commands_valid
        and architecture_valid
        and verifier_valid
    )
    return {
        "valid_json": True,
        "schema_valid": schema_valid,
        "required_field_fraction": round(fields_present / len(REQUIRED_TOP_FIELDS), 4),
        "commands_valid": commands_valid,
        "architecture_valid": architecture_valid,
        "verifier_valid": verifier_valid,
    }


def policy_predictions(parsed: dict[str, Any] | None) -> dict[str, str | None]:
    if not isinstance(parsed, dict):
        return {field: None for field in POLICY_FIELDS}
    architecture = parsed.get("architecture") if isinstance(parsed.get("architecture"), dict) else {}
    verifier = parsed.get("verifier") if isinstance(parsed.get("verifier"), dict) else {}
    return {
        "model_tier": canonical_model_tier(string_or_none(architecture.get("model_tier"))),
        "next_action": canonical_next_action(string_or_none(
            verifier.get("next_action")
            or architecture.get("expected_next_action")
        )),
        "context_policy": canonical_context_policy(string_or_none(architecture.get("context_policy"))),
        "executor_kind": canonical_executor_kind(string_or_none(architecture.get("executor_kind"))),
    }


def canonical_next_action(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower().replace("-", "_")
    return NEXT_ACTION_ALIASES.get(normalized, normalized)


def canonical_model_tier(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower().replace("-", "_")
    return MODEL_TIER_ALIASES.get(normalized, normalized)


def canonical_context_policy(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower().replace("-", "_")
    return CONTEXT_POLICY_ALIASES.get(normalized, normalized)


def canonical_executor_kind(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower().replace("-", "_")
    return EXECUTOR_KIND_ALIASES.get(normalized, normalized)


def expected_policy_labels(
    row: dict[str, Any],
    parsed: dict[str, Any] | None,
    predictions: dict[str, str | None],
    *,
    reference: dict[str, Any] | None = None,
) -> tuple[dict[str, str | None], dict[str, str]]:
    stratum_labels = parse_stratum_labels(row.get("balance_stratum") or row.get("stratum"))
    reference_stratum_labels = parse_stratum_labels(
        (reference or {}).get("balance_stratum") or (reference or {}).get("stratum")
    )
    expected: dict[str, str | None] = {}
    sources: dict[str, str] = {}
    for field in POLICY_FIELDS:
        value, source = expected_from_row(row, field)
        if value is None and reference is not None:
            value, source = expected_from_row(reference, field)
            if source:
                source = f"reference.{source}"
        if value is None and reference is not None:
            value = expected_from_reference_json(reference, field)
            if value is not None:
                source = "reference.assistant_json"
        if value is None and field in stratum_labels:
            value = stratum_labels[field]
            source = "stratum"
        if value is None and field in reference_stratum_labels:
            value = reference_stratum_labels[field]
            source = "reference.stratum"
        if value is None and parsed is not None:
            value = predictions.get(field)
            source = "assistant_json"
        expected[field] = value
        sources[field] = source or "missing"
    return expected, sources


def expected_from_reference_json(row: dict[str, Any], field: str) -> str | None:
    assistant_text, _error = assistant_text_from_row(row)
    if assistant_text is None:
        return None
    parsed = parse_assistant_json(assistant_text)
    predictions = policy_predictions(parsed)
    return predictions.get(field)


def expected_from_row(row: dict[str, Any], field: str) -> tuple[str | None, str | None]:
    candidates = {
        "model_tier": ("expected_model_tier", "model_tier"),
        "next_action": ("expected_next_action", "next_action"),
        "context_policy": ("expected_context_policy", "context_policy"),
        "executor_kind": ("expected_executor_kind", "executor_kind"),
    }[field]
    for key in candidates:
        value = row.get(key)
        if isinstance(value, str) and value:
            return canonical_field_value(field, value), key

    labels = row.get("labels")
    if isinstance(labels, dict):
        value = labels.get(field)
        if isinstance(value, str) and value:
            return canonical_field_value(field, value), f"labels.{field}"

    expected = row.get("expected")
    if isinstance(expected, dict):
        value = expected.get(field)
        if isinstance(value, str) and value:
            return canonical_field_value(field, value), f"expected.{field}"

    return None, None


def canonical_field_value(field: str, value: str) -> str:
    if field == "model_tier":
        return canonical_model_tier(value) or value
    if field == "next_action":
        return canonical_next_action(value) or value
    if field == "context_policy":
        return canonical_context_policy(value) or value
    if field == "executor_kind":
        return canonical_executor_kind(value) or value
    return value


def model_label_for_row(row: dict[str, Any]) -> str:
    value = row.get("model_label") or row.get("label")
    if isinstance(value, str) and value:
        return value
    return MISSING_GROUP


def load_references(path: Path, *, key_field: str) -> dict[Any, dict[str, Any]]:
    references: dict[Any, dict[str, Any]] = {}
    for line_number, row in iter_jsonl(path):
        references[reference_key(row, line_number, key_field)] = row
    return references


def reference_key(row: dict[str, Any], line_number: int, key_field: str) -> Any:
    if key_field in row:
        return row[key_field]
    if key_field == "line_number":
        return row.get("line_number") or line_number
    return row.get(key_field) or row.get("transition_id") or line_number


def parse_stratum_labels(value: Any) -> dict[str, str]:
    if not isinstance(value, str) or not value:
        return {}
    labels: dict[str, str] = {}
    tier_match = re.search(r"(?:^|\|)tier=([^|]+)", value)
    next_match = re.search(r"(?:^|\|)next=([^|]+)", value)
    if tier_match:
        labels["model_tier"] = tier_match.group(1)
    if next_match:
        labels["next_action"] = next_match.group(1)
    return labels


def source_mode_for_row(
    row: dict[str, Any],
    expected: dict[str, str | None],
    *,
    reference: dict[str, Any] | None = None,
) -> str:
    source_mode = row.get("source_mode")
    if isinstance(source_mode, str) and source_mode:
        return source_mode
    if reference is not None:
        source_mode = reference.get("source_mode")
        if isinstance(source_mode, str) and source_mode:
            return source_mode
    stratum = row.get("balance_stratum") or row.get("stratum")
    if isinstance(stratum, str) and "|" in stratum:
        prefix = stratum.split("|", 1)[0]
        if prefix:
            return prefix
    if reference is not None:
        stratum = reference.get("balance_stratum") or reference.get("stratum")
        if isinstance(stratum, str) and "|" in stratum:
            prefix = stratum.split("|", 1)[0]
            if prefix:
                return prefix
    source = row.get("source")
    if isinstance(source, dict):
        schema_mode = source.get("schema_mode")
        if isinstance(schema_mode, str) and schema_mode:
            return schema_mode
    if isinstance(source, str) and source:
        return source
    if expected.get("model_tier") or expected.get("next_action"):
        return "unknown"
    return MISSING_GROUP


def stratum_for_row(
    row: dict[str, Any],
    source_mode: str,
    expected: dict[str, str | None],
    *,
    reference: dict[str, Any] | None = None,
) -> str:
    for key in ("balance_stratum", "stratum"):
        value = row.get(key)
        if isinstance(value, str) and value:
            return value
    if reference is not None:
        for key in ("balance_stratum", "stratum"):
            value = reference.get(key)
            if isinstance(value, str) and value:
                return value
    model_tier = expected.get("model_tier") or "unknown"
    next_action = expected.get("next_action") or "unknown"
    return f"{source_mode}|tier={model_tier}|next={next_action}"


def new_aggregate() -> dict[str, Any]:
    return {
        "rows": 0,
        "normalized_count": 0,
        "valid_json_count": 0,
        "schema_valid_count": 0,
        "commands_valid_count": 0,
        "architecture_valid_count": 0,
        "verifier_valid_count": 0,
        "required_field_fraction_sum": 0.0,
        "correct": Counter(),
        "total": Counter(),
        "expected_counts": {field: Counter() for field in POLICY_FIELDS},
        "predicted_counts": {field: Counter() for field in POLICY_FIELDS},
    }


def update_aggregate(aggregate: dict[str, Any], result: dict[str, Any]) -> None:
    schema = result["schema"]
    aggregate["rows"] += 1
    aggregate["normalized_count"] += int(bool(result.get("normalized")))
    aggregate["valid_json_count"] += int(schema["valid_json"])
    aggregate["schema_valid_count"] += int(schema["schema_valid"])
    aggregate["commands_valid_count"] += int(schema["commands_valid"])
    aggregate["architecture_valid_count"] += int(schema["architecture_valid"])
    aggregate["verifier_valid_count"] += int(schema["verifier_valid"])
    aggregate["required_field_fraction_sum"] += float(schema["required_field_fraction"])
    for field in POLICY_FIELDS:
        expected = result["expected"].get(field)
        predicted = result["predictions"].get(field)
        if expected is not None:
            aggregate["total"][field] += 1
            aggregate["expected_counts"][field][expected] += 1
            aggregate["correct"][field] += int(result["matches"][field] is True)
        if predicted is not None:
            aggregate["predicted_counts"][field][predicted] += 1


def finalize_aggregate(aggregate: dict[str, Any]) -> dict[str, Any]:
    rows = aggregate["rows"]
    output: dict[str, Any] = {
        "rows": rows,
        "normalized_count": aggregate["normalized_count"],
        "normalized_rate": rate(aggregate["normalized_count"], rows),
        "valid_json_count": aggregate["valid_json_count"],
        "valid_json_rate": rate(aggregate["valid_json_count"], rows),
        "schema_valid_count": aggregate["schema_valid_count"],
        "schema_valid_rate": rate(aggregate["schema_valid_count"], rows),
        "commands_valid_rate": rate(aggregate["commands_valid_count"], rows),
        "architecture_valid_rate": rate(aggregate["architecture_valid_count"], rows),
        "verifier_valid_rate": rate(aggregate["verifier_valid_count"], rows),
        "required_field_fraction_mean": (
            round(aggregate["required_field_fraction_sum"] / rows, 4)
            if rows
            else 0.0
        ),
    }
    for field in POLICY_FIELDS:
        total = aggregate["total"][field]
        correct = aggregate["correct"][field]
        output[f"{field}_correct"] = correct
        output[f"{field}_total"] = total
        output[f"{field}_accuracy"] = rate(correct, total)
    output["expected_counts"] = {
        field: dict(sorted(counter.items()))
        for field, counter in aggregate["expected_counts"].items()
    }
    output["predicted_counts"] = {
        field: dict(sorted(counter.items()))
        for field, counter in aggregate["predicted_counts"].items()
    }
    return output


def render_markdown(metrics: dict[str, Any]) -> str:
    overall = metrics["overall"]
    lines = [
        "# OpenClaw Architecture Policy Evaluation",
        "",
        f"- Created at: {metrics['created_at']}",
        f"- Input file: `{metrics['input_file']}`",
        f"- Rows: {overall['rows']}",
        "",
        "## Overall",
        "",
        "| Metric | Count | Rate |",
        "| --- | ---: | ---: |",
        f"| Valid JSON | {overall['valid_json_count']}/{overall['rows']} | {percent(overall['valid_json_rate'])} |",
        f"| Schema valid | {overall['schema_valid_count']}/{overall['rows']} | {percent(overall['schema_valid_rate'])} |",
        f"| Normalized compact output | {overall['normalized_count']}/{overall['rows']} | {percent(overall['normalized_rate'])} |",
        policy_metric_row(overall, "model_tier"),
        policy_metric_row(overall, "next_action"),
        policy_metric_row(overall, "context_policy"),
        policy_metric_row(overall, "executor_kind"),
        "",
        "## By Stratum",
        "",
        group_table(metrics["by_stratum"]),
        "",
        "## By Source Mode",
        "",
        group_table(metrics["by_source_mode"]),
        "",
        "## By Model Label",
        "",
        group_table(metrics["by_model_label"]),
        "",
        "## Label Sources",
        "",
        "| Field | Source counts |",
        "| --- | --- |",
    ]
    for field, counts in metrics["label_sources"].items():
        rendered = ", ".join(f"{key}={value}" for key, value in counts.items()) or "none"
        lines.append(f"| `{field}` | {rendered} |")
    if metrics.get("parse_failures_sample"):
        lines.extend([
            "",
            "## Parse Failures Sample",
            "",
            "| Line | Transition | Error |",
            "| ---: | --- | --- |",
        ])
        for failure in metrics["parse_failures_sample"]:
            lines.append(
                f"| {failure['line_number']} | `{failure.get('transition_id') or ''}` | "
                f"{failure['error']} |"
            )
    return "\n".join(lines).rstrip() + "\n"


def policy_metric_row(metrics: dict[str, Any], field: str) -> str:
    return (
        f"| {field} accuracy | "
        f"{metrics[f'{field}_correct']}/{metrics[f'{field}_total']} | "
        f"{percent(metrics[f'{field}_accuracy'])} |"
    )


def group_table(groups: dict[str, dict[str, Any]]) -> str:
    lines = [
        "| Group | Rows | Schema valid | Model tier | Next action | Context policy | Executor kind |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for group, metrics in groups.items():
        lines.append(
            f"| `{group}` | {metrics['rows']} | {percent(metrics['schema_valid_rate'])} | "
            f"{percent(metrics['model_tier_accuracy'])} | {percent(metrics['next_action_accuracy'])} | "
            f"{percent(metrics['context_policy_accuracy'])} | {percent(metrics['executor_kind_accuracy'])} |"
        )
    return "\n".join(lines)


def iter_jsonl(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL row at {path}:{line_number}") from exc
            if not isinstance(row, dict):
                raise ValueError(f"Expected JSON object at {path}:{line_number}")
            yield line_number, row


def string_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def rate(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 4)


def percent(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.2%}"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    main()
