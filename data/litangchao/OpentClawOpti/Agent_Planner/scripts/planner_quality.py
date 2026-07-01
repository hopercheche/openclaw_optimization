from __future__ import annotations

import statistics
from collections import Counter
from typing import Any


VALIDATION_HINTS = (
    "validate",
    "validation",
    "verify",
    "check",
    "sanity",
    "csv.reader",
    "assert",
)
SCRIPT_HINTS = (
    "python -c",
    "python3 -c",
    "cat >",
    "cat <<",
    "EOF",
    "python <<",
    "python3 <<",
)
RISKY_COMMAND_HINTS = (
    "rm -rf",
    "sudo ",
    "chmod -r",
    "chown -r",
    "mkfs",
    ":(){",
)
SIMPLE_ACTION_PREFIXES = (
    "cat ",
    "head ",
    "tail ",
    "ls",
    "find ",
    "rg ",
    "sed ",
    "python ",
    "python3 ",
    "./",
)
LOW_PROGRESS_COMMANDS = (
    "python --version",
    "python3 --version",
    "python -V",
    "python3 -V",
    "pwd",
    "whoami",
    "which python",
    "which python3",
)
CONCRETE_WORK_HINTS = (
    "/app/",
    ".csv",
    ".json",
    ".jsonl",
    ".py",
    ".txt",
    ".md",
    ".tsv",
    ".xml",
    ".yaml",
    ".yml",
)


def extract_command_texts(parsed: dict[str, Any] | None) -> list[str]:
    if not parsed or not isinstance(parsed.get("commands"), list):
        return []
    command_texts: list[str] = []
    for command in parsed["commands"]:
        if not isinstance(command, dict):
            continue
        keystrokes = command.get("keystrokes")
        if isinstance(keystrokes, str):
            command_texts.append(keystrokes)
    return command_texts


def command_quality_features(
    parsed: dict[str, Any] | None,
    *,
    schema: dict[str, Any] | None = None,
    long_command_chars: int = 120,
) -> dict[str, Any]:
    command_texts = extract_command_texts(parsed)
    max_command_chars = max((len(command) for command in command_texts), default=0)
    task_complete = parsed.get("task_complete") if parsed else None
    validation_only = bool(command_texts) and all(
        contains_any(command, VALIDATION_HINTS)
        for command in command_texts
    )
    low_progress_probe = bool(command_texts) and all(
        is_low_progress_probe(command)
        for command in command_texts
    )
    concrete_work_command = any(
        contains_any(command, CONCRETE_WORK_HINTS)
        for command in command_texts
    )
    features = {
        "command_count": len(command_texts),
        "max_command_chars": max_command_chars,
        "long_command": any(len(command) > long_command_chars for command in command_texts),
        "multiline_command": any("\n" in command.strip() for command in command_texts),
        "script_like_command": any(contains_any(command, SCRIPT_HINTS) for command in command_texts),
        "risky_command": any(contains_any(command, RISKY_COMMAND_HINTS) for command in command_texts),
        "validation_only_command": validation_only,
        "complete_with_commands": task_complete is True and bool(command_texts),
        "incomplete_without_commands": task_complete is False and not command_texts,
        "low_progress_probe_command": low_progress_probe,
        "concrete_work_command": concrete_work_command,
        "simple_action_command": bool(command_texts)
        and all(command.strip().lower().startswith(SIMPLE_ACTION_PREFIXES) for command in command_texts),
    }
    if schema is not None:
        features["schema_valid"] = bool(schema.get("schema_valid", False))
        features["valid_json"] = bool(schema.get("valid_json", False))
        features["task_complete_bool"] = bool(schema.get("task_complete_bool", False))
    return features


def failure_labels(
    row: dict[str, Any],
    parsed: dict[str, Any] | None,
    *,
    long_command_chars: int = 120,
    low_overlap_threshold: float = 0.05,
) -> list[str]:
    schema = row.get("schema") or {}
    features = command_quality_features(parsed, schema=schema, long_command_chars=long_command_chars)
    labels: list[str] = []
    if not schema.get("valid_json", parsed is not None):
        labels.append("invalid_json")
    if not schema.get("schema_valid", False):
        labels.append("schema_invalid")
    if row.get("command_overlap", 0.0) < low_overlap_threshold:
        labels.append("low_command_overlap")
    for label in (
        "long_command",
        "multiline_command",
        "script_like_command",
        "risky_command",
        "validation_only_command",
        "complete_with_commands",
        "incomplete_without_commands",
        "low_progress_probe_command",
    ):
        if features[label]:
            labels.append(label)
    return labels or ["ok"]


def summarize_quality_metrics(
    rows: list[dict[str, Any]],
    *,
    long_command_chars: int = 120,
) -> dict[str, Any]:
    total = len(rows) or 1
    feature_rows = [
        row.get("command_quality")
        if isinstance(row.get("command_quality"), dict)
        else command_quality_features(row.get("parsed"), schema=row.get("schema"), long_command_chars=long_command_chars)
        for row in rows
    ]
    label_counts = Counter(
        label
        for features in feature_rows
        for label in (
            "long_command",
            "multiline_command",
            "script_like_command",
            "risky_command",
            "validation_only_command",
            "complete_with_commands",
            "incomplete_without_commands",
            "low_progress_probe_command",
        )
        if features.get(label)
    )
    max_command_chars = [int(features.get("max_command_chars", 0)) for features in feature_rows]
    command_counts = [int(features.get("command_count", 0)) for features in feature_rows]
    return {
        "long_command_chars": long_command_chars,
        "quality_label_counts": dict(sorted(label_counts.items())),
        "long_command_rate": round(label_counts.get("long_command", 0) / total, 4),
        "multiline_command_rate": round(label_counts.get("multiline_command", 0) / total, 4),
        "script_like_command_rate": round(label_counts.get("script_like_command", 0) / total, 4),
        "risky_command_rate": round(label_counts.get("risky_command", 0) / total, 4),
        "validation_only_command_rate": round(label_counts.get("validation_only_command", 0) / total, 4),
        "complete_with_commands_rate": round(label_counts.get("complete_with_commands", 0) / total, 4),
        "incomplete_without_commands_rate": round(label_counts.get("incomplete_without_commands", 0) / total, 4),
        "low_progress_probe_command_rate": round(label_counts.get("low_progress_probe_command", 0) / total, 4),
        "mean_command_count": round(statistics.mean(command_counts) if command_counts else 0.0, 4),
        "mean_max_command_chars": round(statistics.mean(max_command_chars) if max_command_chars else 0.0, 4),
        "p95_max_command_chars": percentile(max_command_chars, 0.95),
    }


def score_candidate(
    row: dict[str, Any],
    parsed: dict[str, Any] | None,
    *,
    long_command_chars: int = 120,
) -> dict[str, Any]:
    schema = row.get("schema") or {}
    features = command_quality_features(parsed, schema=schema, long_command_chars=long_command_chars)
    score = 0.0
    reasons: list[str] = []
    if schema.get("schema_valid"):
        score += 100.0
        reasons.append("schema_valid:+100")
    elif schema.get("valid_json"):
        score += 25.0
        reasons.append("valid_json:+25")
    else:
        score -= 50.0
        reasons.append("invalid_json:-50")
    if schema.get("task_complete_bool"):
        score += 5.0
    if features["simple_action_command"]:
        score += 3.0
    if features["concrete_work_command"]:
        score += 2.0
    penalties = {
        "long_command": 18.0,
        "multiline_command": 25.0,
        "script_like_command": 20.0,
        "risky_command": 35.0,
        "validation_only_command": 12.0,
        "complete_with_commands": 6.0,
        "incomplete_without_commands": 8.0,
        "low_progress_probe_command": 18.0,
    }
    for label, penalty in penalties.items():
        if features[label]:
            score -= penalty
            reasons.append(f"{label}:-{penalty:g}")
    if features["command_count"] > 2:
        penalty = min(10.0, (features["command_count"] - 2) * 2.0)
        score -= penalty
        reasons.append(f"many_commands:-{penalty:g}")
    if features["max_command_chars"] > 0:
        length_penalty = min(6.0, features["max_command_chars"] / max(long_command_chars, 1) * 2.0)
        score -= length_penalty
    score -= min(4.0, float(row.get("new_tokens") or 0) / 256.0)
    return {
        "score": round(score, 4),
        "reasons": reasons,
        "features": features,
    }


def contains_any(value: str, needles: tuple[str, ...]) -> bool:
    lowered = value.lower()
    return any(needle.lower() in lowered for needle in needles)


def is_low_progress_probe(command: str) -> bool:
    stripped = command.strip()
    if stripped.endswith("\n"):
        stripped = stripped[:-1].strip()
    lowered = stripped.lower()
    return lowered in {item.lower() for item in LOW_PROGRESS_COMMANDS}


def percentile(values: list[int], p: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * p))))
    return ordered[index]
