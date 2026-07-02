#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[5]
if str(PROJECT_ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from openclaw.planner_profile_model import strip_profile_hints  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build an OpenClaw benchmark suite with explicit planner profile hints stripped.",
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=PROJECT_ROOT / "benchmarks" / "tasks" / "030_multisource_planner_generalization_suite.json",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--output-name", default="030_multisource_planner_generalization_suite.no_hint.json")
    args = parser.parse_args()

    tasks = json.loads(args.input.read_text(encoding="utf-8"))
    if not isinstance(tasks, list):
        raise SystemExit(f"Expected a list of benchmark tasks: {args.input}")

    stripped_tasks = [strip_task(task) for task in tasks]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    tasks_dir = args.output_dir / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    output_path = tasks_dir / args.output_name
    output_path.write_text(
        json.dumps(stripped_tasks, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    summary = {
        "input": str(args.input),
        "tasks_dir": str(tasks_dir),
        "output": str(output_path),
        "tasks": len(stripped_tasks),
        "split_counts": split_counts(stripped_tasks),
    }
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def strip_task(task: dict[str, Any]) -> dict[str, Any]:
    copied = json.loads(json.dumps(task, ensure_ascii=False))
    goal = str(copied.get("goal", ""))
    copied["goal"] = strip_profile_hints(goal)
    copied["description"] = f"{copied.get('description', '')} Explicit planner profile hints stripped.".strip()
    copied["no_hint"] = True
    return copied


def split_counts(tasks: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for task in tasks:
        split = str(task.get("split", "dev"))
        counts[split] = counts.get(split, 0) + 1
    return dict(sorted(counts.items()))


if __name__ == "__main__":
    main()
