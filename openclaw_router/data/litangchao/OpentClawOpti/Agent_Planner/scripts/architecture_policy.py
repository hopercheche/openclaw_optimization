from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
AGENT_PLANNER_ROOT = SCRIPT_DIR.parent
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


TOOL_PRIORS = {
    "command_runner": {
        "model_tier": "medium",
        "context_policy": "progressive_context+memory_retrieval+success_criteria",
        "executor_kind": "workspace_tool",
    },
    "deploy_runner": {
        "model_tier": "large",
        "context_policy": "progressive_context+memory_retrieval+success_criteria",
        "executor_kind": "workspace_tool",
    },
    "file_writer": {
        "model_tier": "medium",
        "context_policy": "progressive_context+memory_retrieval+success_criteria",
        "executor_kind": "workspace_tool",
    },
    "goal_analyzer": {
        "model_tier": "small",
        "context_policy": "goal_boundary",
        "executor_kind": "read_only_agent",
        "next_action": "next_subtask",
    },
    "mcp_tool_runner": {
        "model_tier": "medium",
        "context_policy": "progressive_context+memory_retrieval+success_criteria",
        "executor_kind": "external_tool",
    },
    "mobile_cli_runner": {
        "model_tier": "medium",
        "context_policy": "progressive_context+memory_retrieval+success_criteria",
        "executor_kind": "external_tool",
    },
    "mobile_gui_runner": {
        "model_tier": "medium",
        "context_policy": "progressive_context+memory_retrieval+success_criteria",
        "executor_kind": "external_tool",
    },
    "planner": {
        "model_tier": "small",
        "context_policy": "progressive_context+candidate_scores",
        "executor_kind": "read_only_agent",
        "next_action": "next_subtask",
    },
    "risk_model": {
        "model_tier": "small",
        "context_policy": "permission_policy+risk_terms",
        "executor_kind": "policy_gate",
        "next_action": "next_subtask",
    },
    "safety_guard": {
        "model_tier": "medium",
        "context_policy": "permission_policy+risk_terms",
        "executor_kind": "policy_gate",
        "next_action": "next_subtask",
    },
    "verifier": {
        "model_tier": "medium",
        "context_policy": "execution_evidence+critique_history",
        "executor_kind": "verifier",
        "next_action": "next_subtask",
    },
    "workspace_inspector": {
        "model_tier": "small",
        "context_policy": "workspace_snapshot",
        "executor_kind": "read_only_agent",
        "next_action": "next_subtask",
    },
}
VARIABLE_EXECUTION_TOOLS = {
    "command_runner",
    "deploy_runner",
    "file_writer",
    "mcp_tool_runner",
    "mobile_cli_runner",
    "mobile_gui_runner",
}
DANGEROUS_TERMS = {
    "delete",
    "remove",
    "rm ",
    "drop",
    "prod",
    "production",
    "secret",
    "credential",
    "token",
    "删除",
    "清空",
    "转账",
    "支付",
    "隐私",
    "联系人",
    "短信",
    "位置",
    "照片",
}
DANGEROUS_WORD_RE = re.compile(
    r"\b(?:delete|remove|drop|prod|production|secret|credential|token)\b|(?:^|\s)rm\s",
    re.IGNORECASE,
)
DANGEROUS_CJK_TERMS = {"删除", "清空", "转账", "支付", "隐私", "联系人", "短信", "位置", "照片"}
TOOL_UNRELIABILITY_RE = re.compile(
    r"\b(?:recoverable tool hazard|specification drift|spec drift|invocation error|execution failure|"
    r"output drift|cross-source conflict|missing tool|blocked path|tool unavailable|tool failure|"
    r"implicit semantic failure|semantic anomaly|corrupted output|corrupted tool output|"
    r"stale success signal|transient failure|permanent failure)\b",
    re.IGNORECASE,
)
TOOL_UNRELIABILITY_CJK_TERMS = {
    "工具失败",
    "工具不可用",
    "调用失败",
    "规格漂移",
    "输出冲突",
    "交叉来源冲突",
    "隐性失败",
    "语义异常",
    "输出污染",
}
UNSOLVABLE_TASK_RE = re.compile(
    r"\b(?:unsolvable task|impossible task|no valid recovery path|cannot be completed|"
    r"cannot complete|required tool is missing|required data is unavailable)\b",
    re.IGNORECASE,
)
UNSOLVABLE_TASK_CJK_TERMS = {"不可解", "无法完成", "没有有效恢复路径", "缺少必要工具", "必要数据不可用"}
ACTIVE_ACTION_RE = re.compile(
    r"^(?:Perturbation active action|Active action|Selected action risk):\s*(?P<action>.+)$",
    re.IGNORECASE | re.MULTILINE,
)
PERMISSION_NEXT_ACTION_GUARDS = {
    "ACCEPT_EDITS": "next_subtask",
    "BYPASS": "next_subtask",
    "DEFAULT": "await_human",
    "DONT_ASK": "replan",
    "EXPLORE": "replan",
}
POLICY_FIELDS = ("model_tier", "verifier_next_action", "context_policy", "executor_kind")


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
    prompt_context = policy_context_for_row(row)
    compact, rules = compact_from_full_policy(
        full,
        permission_mode=permission_mode_for_row(row),
        context_task_id=prompt_context.get("task_id"),
        context_tool_name=prompt_context.get("tool_name"),
        context_action=prompt_context.get("action"),
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
    context_task_id: str | None = None,
    context_tool_name: str | None = None,
    context_action: str | None = None,
    apply_tool_priors: bool = True,
    apply_next_action_priors: bool = True,
    apply_permission_guards: bool = True,
    apply_hazard_guards: bool = True,
) -> tuple[dict[str, str], list[str]]:
    architecture = parsed.get("architecture") if isinstance(parsed, dict) and isinstance(parsed.get("architecture"), dict) else {}
    verifier = parsed.get("verifier") if isinstance(parsed, dict) and isinstance(parsed.get("verifier"), dict) else {}
    raw_tool_name = string_or_none(architecture.get("tool_name"))
    if not raw_tool_name and context_tool_name:
        raw_tool_name = context_tool_name
    tool_name = canonical_tool_name(raw_tool_name or "planner")
    action_text = string_or_none(architecture.get("action"))
    if action_text is None and tool_name == "deploy_runner":
        action_text = context_action
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

    prior = TOOL_PRIORS.get(tool_name, {}) if apply_tool_priors else {}
    if apply_tool_priors:
        if prior.get("model_tier") and prior["model_tier"] != model_tier:
            model_tier = prior["model_tier"]
            rules.append("tool_prior:model_tier")
        if prior.get("context_policy") and prior["context_policy"] != context_policy:
            context_policy = prior["context_policy"]
            rules.append("tool_prior:context_policy")
        if prior.get("executor_kind") and prior["executor_kind"] != executor_kind:
            executor_kind = prior["executor_kind"]
            rules.append("tool_prior:executor_kind")
    if apply_tool_priors and apply_next_action_priors and prior.get("next_action") and prior["next_action"] != next_action:
        next_action = prior["next_action"]
        rules.append("tool_prior:next_action")
    guarded_next_action = permission_guard_next_action(
        permission_mode,
        tool_name,
        next_action,
        action=action_text,
        apply_permission_mode_guards=apply_permission_guards,
        apply_hazard_guards=apply_hazard_guards,
    )
    if guarded_next_action != next_action:
        next_action = guarded_next_action
        rules.append(f"permission_guard:next_action:{permission_mode}")

    return {
        "task_id": string_or_none(architecture.get("task_id")) or context_task_id or "unknown",
        "tool_name": tool_name,
        "model_tier": model_tier,
        "context_policy": context_policy,
        "executor_kind": executor_kind,
        "verifier_next_action": next_action,
    }, rules


def policy_from_tool_context(
    *,
    tool_name: str,
    permission_mode: str | None,
    task_id: str = "unknown",
    action: str | None = None,
    apply_tool_priors: bool = True,
    apply_next_action_priors: bool = True,
    apply_permission_guards: bool = True,
    apply_hazard_guards: bool = True,
) -> tuple[dict[str, str], list[str]]:
    parsed = {
        "architecture": {
            "task_id": task_id,
            "tool_name": tool_name,
            "action": action or "",
            "model_tier": "unknown",
            "context_policy": "unknown",
            "executor_kind": "unknown",
            "expected_next_action": "unknown",
        },
        "verifier": {"next_action": "unknown"},
    }
    return compact_from_full_policy(
        parsed,
        permission_mode=permission_mode,
        context_action=action,
        apply_tool_priors=apply_tool_priors,
        apply_next_action_priors=apply_next_action_priors,
        apply_permission_guards=apply_permission_guards,
        apply_hazard_guards=apply_hazard_guards,
    )


def expected_policy_from_runtime(
    subtask: dict[str, Any],
    verifier: dict[str, Any] | None,
) -> dict[str, str]:
    verifier_data = (verifier or {}).get("data", {})
    return {
        "task_id": string_or_none(subtask.get("task_id")) or "unknown",
        "tool_name": canonical_tool_name(string_or_none(subtask.get("tool_name")) or "planner"),
        "model_tier": canonical_model_tier(string_or_none(subtask.get("model_tier"))) or "unknown",
        "context_policy": canonical_context_policy(string_or_none(subtask.get("context_policy"))) or "unknown",
        "executor_kind": canonical_executor_kind(string_or_none(subtask.get("executor_kind"))) or "unknown",
        "verifier_next_action": (
            canonical_next_action(
                string_or_none(verifier_data.get("next_action"))
                or string_or_none(subtask.get("expected_next_action"))
            )
            or "unknown"
        ),
    }


def score_compact_policy(
    prediction: dict[str, str],
    expected: dict[str, str],
) -> dict[str, Any]:
    matches = {
        field: prediction.get(field) == expected.get(field)
        for field in POLICY_FIELDS
    }
    return {
        "matches": matches,
        "exact_match": all(matches.values()),
    }


def canonical_tool_name(value: str) -> str:
    return value.strip().lower().replace("-", "_")


def permission_guard_next_action(
    permission_mode: str | None,
    tool_name: str,
    next_action: str,
    *,
    action: str | None = None,
    apply_permission_mode_guards: bool = True,
    apply_hazard_guards: bool = True,
) -> str:
    if apply_hazard_guards and has_unsolvable_task_term(action or ""):
        return "await_human"
    if tool_name not in VARIABLE_EXECUTION_TOOLS:
        return next_action
    if apply_permission_mode_guards and permission_mode not in PERMISSION_NEXT_ACTION_GUARDS:
        return next_action
    if apply_permission_mode_guards and permission_mode in {"DONT_ASK", "EXPLORE"}:
        return PERMISSION_NEXT_ACTION_GUARDS[permission_mode]
    if apply_hazard_guards and has_recoverable_tool_hazard(action or ""):
        return "replan"
    if apply_hazard_guards and has_dangerous_action_term(action or ""):
        return "await_human"
    if not apply_permission_mode_guards:
        return next_action
    return PERMISSION_NEXT_ACTION_GUARDS[permission_mode]


def has_dangerous_action_term(action: str) -> bool:
    if DANGEROUS_WORD_RE.search(action):
        return True
    return any(term in action for term in DANGEROUS_CJK_TERMS)


def has_recoverable_tool_hazard(action: str) -> bool:
    if TOOL_UNRELIABILITY_RE.search(action):
        return True
    return any(term in action for term in TOOL_UNRELIABILITY_CJK_TERMS)


def has_unsolvable_task_term(action: str) -> bool:
    if UNSOLVABLE_TASK_RE.search(action):
        return True
    return any(term in action for term in UNSOLVABLE_TASK_CJK_TERMS)


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


def policy_context_for_row(row: dict[str, Any]) -> dict[str, str]:
    text_parts = [
        row.get(key)
        for key in ("prompt", "task_preview", "input", "user")
        if isinstance(row.get(key), str)
    ]
    text = "\n".join(text_parts)
    candidate = extract_subtask_candidate(text)
    title = string_or_none(candidate.get("title")) or ""
    objective = string_or_none(candidate.get("objective")) or ""
    task_id = string_or_none(candidate.get("task_id")) or ""
    focused_text = "\n".join(part for part in [title, objective] if part)
    active_action = extract_active_action_context(text)
    tool_name = infer_tool_from_prompt(focused_text) or infer_tool_from_prompt(text)
    return {
        "task_id": task_id,
        "tool_name": tool_name or "",
        "action": "\n".join(part for part in [focused_text, active_action] if part) or text,
    }


def extract_active_action_context(text: str) -> str:
    matches = [match.group("action").strip() for match in ACTIVE_ACTION_RE.finditer(text)]
    return "\n".join(match for match in matches if match)


def extract_subtask_candidate(text: str) -> dict[str, Any]:
    marker = "Subtask candidate:"
    marker_index = text.find(marker)
    if marker_index < 0:
        return {}
    start = text.find("{", marker_index + len(marker))
    if start < 0:
        return {}
    candidate = extract_json_object(text, start)
    if candidate is None:
        return {}
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


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


def infer_tool_from_prompt(text: str) -> str | None:
    normalized = text.lower()
    if "mobile gui" in normalized or "gui workflow" in normalized:
        return "mobile_gui_runner"
    if "mobile cli" in normalized or "cli workflow" in normalized:
        return "mobile_cli_runner"
    if "mcp" in normalized or "workflow tool" in normalized:
        return "mcp_tool_runner"
    if "production deployment" in normalized or "deploy" in normalized:
        return "deploy_runner"
    if "external workflow safety" in normalized or "safety policy" in normalized:
        return "safety_guard"
    if "define audit boundary" in normalized or "goal boundary" in normalized:
        return "goal_analyzer"
    if "permission posture" in normalized or "permission decision" in normalized:
        return "risk_model"
    if "residual risk" in normalized or "verifier" in normalized or "verify " in normalized or "verification" in normalized:
        return "verifier"
    if "bounded plan" in normalized or "plan candidates" in normalized or "tree-of-thought" in normalized:
        return "planner"
    if "workspace" in normalized and ("inspect" in normalized or "snapshot" in normalized):
        return "workspace_inspector"
    if "implementation change" in normalized or ("file" in normalized and ("write" in normalized or "edit" in normalized)):
        return "file_writer"
    if "run validation" in normalized or "command" in normalized or "test" in normalized or "validation" in normalized:
        return "command_runner"
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
