#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


AGENT_PLANNER_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVAL_RUNS = AGENT_PLANNER_ROOT / "eval_runs"
POLICY_FIELDS = ("model_tier", "next_action", "context_policy", "executor_kind")
SUMMARY_COLUMNS = (
    "rows",
    "schema_valid_rate",
    "normalized_count",
    "model_tier_accuracy",
    "next_action_accuracy",
    "context_policy_accuracy",
    "executor_kind_accuracy",
)
JSON_SUMMARY_FILES = ("summary.json", "metrics.json")
TARGET_FILES = JSON_SUMMARY_FILES + ("generations.jsonl",)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Summarize OpenClaw architecture-policy eval run outputs.",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="Eval output directories or summary.json / metrics.json / generations.jsonl files.",
    )
    parser.add_argument(
        "--format",
        choices=("json", "markdown", "md"),
        default=None,
        help="Output format. Defaults to JSON, or Markdown when --output ends in .md.",
    )
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument(
        "--no-recursive",
        action="store_true",
        help="Only inspect the provided directories themselves.",
    )
    args = parser.parse_args()

    paths = args.paths or [DEFAULT_EVAL_RUNS]
    summary = summarize_paths(paths, recursive=not args.no_recursive)
    output_format = resolve_output_format(args.format, args.output)
    rendered = (
        render_markdown(summary)
        if output_format == "markdown"
        else json.dumps(summary, ensure_ascii=False, indent=2) + "\n"
    )
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")


def summarize_paths(paths: list[Path], *, recursive: bool = True) -> dict[str, Any]:
    runs: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for source in discover_sources(paths, recursive=recursive):
        record, reason = load_source_record(source)
        if record is None:
            skipped.append({"path": str(source), "reason": reason or "unsupported_source"})
            continue
        runs.append(record)

    runs.sort(key=lambda row: (row["run_dir"], row["source_file"]))
    return {
        "columns": list(SUMMARY_COLUMNS),
        "runs": runs,
        "skipped": skipped,
    }


def discover_sources(paths: list[Path], *, recursive: bool) -> list[Path]:
    discovered: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        candidates: list[Path] = []
        if path.is_file():
            candidates.append(path)
        elif path.is_dir():
            if any((path / name).is_file() for name in TARGET_FILES):
                candidates.append(path)
            glob = path.rglob if recursive else path.glob
            for file_name in TARGET_FILES:
                for child in glob(file_name):
                    candidates.append(child.parent)
        else:
            candidates.append(path)

        for candidate in candidates:
            key = str(candidate.resolve())
            if key not in seen:
                seen.add(key)
                discovered.append(candidate)
    return discovered


def load_source_record(source: Path) -> tuple[dict[str, Any] | None, str | None]:
    if not source.exists():
        return None, "path_not_found"
    if source.is_file():
        if source.name in JSON_SUMMARY_FILES:
            return load_json_summary_record(source)
        if source.name == "generations.jsonl":
            return load_generations_record(source), None
        return None, "unsupported_file_name"

    saw_json_summary = False
    unsupported_json_reasons: list[str] = []
    for file_name in JSON_SUMMARY_FILES:
        candidate = source / file_name
        if not candidate.is_file():
            continue
        saw_json_summary = True
        record, reason = load_json_summary_record(candidate)
        if record is not None:
            return record, None
        unsupported_json_reasons.append(f"{file_name}:{reason or 'unsupported_metrics_shape'}")

    generations = source / "generations.jsonl"
    if not saw_json_summary and generations.is_file():
        return load_generations_record(generations), None
    if saw_json_summary:
        return None, ";".join(unsupported_json_reasons)
    return None, "no_supported_output_files"


def load_json_summary_record(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return None, f"invalid_json:{exc}"
    if not isinstance(data, dict):
        return None, "json_root_not_object"

    metrics = select_metrics_payload(data)
    if metrics is None:
        return None, "missing_architecture_policy_metrics"
    return record_from_metrics(path.parent, path, metrics), None


def select_metrics_payload(data: dict[str, Any]) -> dict[str, Any] | None:
    candidates: list[dict[str, Any]] = []
    for key in ("overall", "metrics", "result"):
        value = data.get(key)
        if isinstance(value, dict):
            candidates.append(value)
    summary = data.get("summary")
    if isinstance(summary, dict):
        if isinstance(summary.get("overall"), dict):
            candidates.append(summary["overall"])
        candidates.append(summary)
    candidates.append(data)

    for candidate in candidates:
        if has_policy_metric(candidate):
            return candidate
    return None


def has_policy_metric(metrics: dict[str, Any]) -> bool:
    return any(
        f"{field}_accuracy" in metrics
        or f"{field}_correct" in metrics
        or f"{field}_total" in metrics
        for field in POLICY_FIELDS
    )


def record_from_metrics(run_dir: Path, source_file: Path, metrics: dict[str, Any]) -> dict[str, Any]:
    rows = first_int(metrics, ("rows", "generation_examples", "examples_scored"))
    record = base_record(run_dir, source_file)
    record["rows"] = rows
    record["schema_valid_rate"] = first_rate(metrics, ("schema_valid_rate",))
    if record["schema_valid_rate"] is None:
        schema_count = first_int(metrics, ("schema_valid_count",))
        record["schema_valid_rate"] = divide(schema_count, rows)
    record["normalized_count"] = first_int(metrics, ("normalized_count",))
    if record["normalized_count"] is None:
        normalized_rate = first_number(metrics, ("normalized_rate",))
        record["normalized_count"] = (
            int(round(normalized_rate * rows))
            if normalized_rate is not None and rows is not None
            else None
        )
    for field in POLICY_FIELDS:
        accuracy_key = f"{field}_accuracy"
        record[accuracy_key] = first_rate(metrics, (accuracy_key,))
        if record[accuracy_key] is None:
            correct = first_int(metrics, (f"{field}_correct",))
            total = first_int(metrics, (f"{field}_total",))
            record[accuracy_key] = divide(correct, total)
    return record


def load_generations_record(path: Path) -> dict[str, Any]:
    rows = 0
    schema_valid_count = 0
    normalized_count = 0
    correct = {field: 0 for field in POLICY_FIELDS}
    total = {field: 0 for field in POLICY_FIELDS}

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

            rows += 1
            schema = row.get("schema")
            if isinstance(schema, dict) and schema.get("schema_valid") is True:
                schema_valid_count += 1
            if row.get("normalized") is True or row.get("normalized_compact") is True:
                normalized_count += 1

            for field in POLICY_FIELDS:
                match = policy_match(row, field)
                if match is not None:
                    total[field] += 1
                    correct[field] += int(match)

    record = base_record(path.parent, path)
    record["rows"] = rows
    record["schema_valid_rate"] = divide(schema_valid_count, rows)
    record["normalized_count"] = normalized_count
    for field in POLICY_FIELDS:
        record[f"{field}_accuracy"] = divide(correct[field], total[field])
    return record


def policy_match(row: dict[str, Any], field: str) -> bool | None:
    for container_name in ("matches", "policy_matches"):
        container = row.get(container_name)
        if isinstance(container, dict) and isinstance(container.get(field), bool):
            return container[field]

    direct_match = row.get(f"{field}_match")
    if isinstance(direct_match, bool):
        return direct_match

    expected = policy_value(row, "expected", field)
    predicted = policy_value(row, "predictions", field)
    if expected is None or predicted is None:
        return None
    return expected == predicted


def policy_value(row: dict[str, Any], container_name: str, field: str) -> str | None:
    container = row.get(container_name)
    if isinstance(container, dict):
        value = container.get(field)
        if isinstance(value, str):
            return value

    prefix = "expected" if container_name == "expected" else "predicted"
    direct_keys = [f"{prefix}_{field}"]
    if field == "next_action":
        direct_keys.append(f"{prefix}_next_action")
    for key in direct_keys:
        value = row.get(key)
        if isinstance(value, str):
            return value
    return None


def base_record(run_dir: Path, source_file: Path) -> dict[str, Any]:
    return {
        "run_name": display_run_name(run_dir),
        "run_dir": str(run_dir),
        "source_file": str(source_file),
        "source_type": source_file.name,
    }


def display_run_name(run_dir: Path) -> str:
    parent_name = run_dir.parent.name
    if parent_name and (
        parent_name.endswith("_eval")
        or parent_name.startswith("202")
        or "architecture_policy" in parent_name
    ):
        return f"{parent_name}/{run_dir.name}"
    return run_dir.name


def first_int(metrics: dict[str, Any], keys: tuple[str, ...]) -> int | None:
    value = first_number(metrics, keys)
    if value is None:
        return None
    return int(value)


def first_rate(metrics: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    value = first_number(metrics, keys)
    if value is None:
        return None
    return round(float(value), 4)


def first_number(metrics: dict[str, Any], keys: tuple[str, ...]) -> float | int | None:
    for key in keys:
        value = metrics.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int | float):
            return value
    return None


def divide(numerator: int | None, denominator: int | None) -> float | None:
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return round(numerator / denominator, 4)


def resolve_output_format(requested: str | None, output: Path | None) -> str:
    if requested in ("markdown", "md"):
        return "markdown"
    if requested == "json":
        return "json"
    if output is not None and output.suffix.lower() in {".md", ".markdown"}:
        return "markdown"
    return "json"


def render_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# OpenClaw Architecture Policy Run Summary",
        "",
        "| Run | Rows | Schema valid | Normalized | Model tier | Next action | Context policy | Executor kind |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for run in summary["runs"]:
        lines.append(
            "| "
            + " | ".join([
                markdown_cell(run["run_name"]),
                render_count(run.get("rows")),
                render_percent(run.get("schema_valid_rate")),
                render_count(run.get("normalized_count")),
                render_percent(run.get("model_tier_accuracy")),
                render_percent(run.get("next_action_accuracy")),
                render_percent(run.get("context_policy_accuracy")),
                render_percent(run.get("executor_kind_accuracy")),
            ])
            + " |"
        )
    if summary.get("skipped"):
        lines.extend(["", "## Skipped", "", "| Path | Reason |", "| --- | --- |"])
        for item in summary["skipped"]:
            lines.append(f"| {markdown_cell(item['path'])} | {markdown_cell(item['reason'])} |")
    return "\n".join(lines).rstrip() + "\n"


def markdown_cell(value: Any) -> str:
    return str(value).replace("|", "\\|")


def render_count(value: Any) -> str:
    if value is None:
        return "n/a"
    return str(value)


def render_percent(value: Any) -> str:
    if not isinstance(value, int | float):
        return "n/a"
    return f"{value:.2%}"


if __name__ == "__main__":
    main()
