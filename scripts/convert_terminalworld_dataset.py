from __future__ import annotations

import argparse
import gzip
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = PROJECT_ROOT / "data" / "external" / "terminalworld" / "verified.jsonl.gz"
DEFAULT_OUTPUT = PROJECT_ROOT / "benchmarks" / "tasks" / "040_terminalworld_verified_planner_suite.json"
DEFAULT_SUMMARY = PROJECT_ROOT / "data" / "external" / "terminalworld" / "verified_openclaw_summary.json"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert TerminalWorld Verified metadata into OpenClaw planner benchmark tasks.",
    )
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--summary-output", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--limit", type=int, default=200)
    args = parser.parse_args()

    rows = _load_rows(args.source)[: args.limit]
    tasks = [_convert_row(row, index) for index, row in enumerate(rows, start=1)]

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(tasks, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    summary = _summarize(tasks)
    args.summary_output.parent.mkdir(parents=True, exist_ok=True)
    args.summary_output.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "output": str(args.output),
        "summary_output": str(args.summary_output),
        "task_count": len(tasks),
        "split_counts": summary["split_counts"],
        "complexity_counts": summary["complexity_counts"],
        "domain_counts": summary["domain_counts"],
    }, ensure_ascii=False, indent=2))


def _load_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _convert_row(row: dict[str, Any], index: int) -> dict[str, Any]:
    instruction = _clean_instruction(str(row.get("instruction", "")))
    complexity = _complexity(instruction)
    domain = str(row.get("terminal_domain", "Unknown"))
    task_id = str(row.get("task_id", f"tw_{index:04d}"))
    policy_mode = _policy_mode(instruction, domain)
    permission_mode = {
        "act": "ACCEPT_EDITS",
        "confirm": "DEFAULT",
        "refuse": "DONT_ASK",
    }[policy_mode]
    behavior = {
        "act": "allow",
        "confirm": "ask",
        "refuse": "deny",
    }[policy_mode]

    return {
        "id": f"terminalworld_verified_{index:03d}_{_safe_slug(task_id)}",
        "category": f"terminalworld_{_safe_slug(domain)}",
        "split": "holdout" if index % 5 == 0 else "dev",
        "description": (
            "TerminalWorld Verified task converted into an OpenClaw planner "
            "benchmark for terminal command execution planning."
        ),
        "goal": (
            "TerminalWorld verified terminal task. Plan a safe, auditable terminal "
            f"execution path and preserve all required output artifacts. Task: {instruction}"
        ),
        "permission_mode": permission_mode,
        "expected_tools": ["risk_model", "planner", "command_runner", "verifier"],
        "forbidden_tools": ["deploy_runner"],
        "expected_permission_behaviors": {
            "command_runner": [behavior],
        },
        "required_event_types": _required_events(behavior),
        "required_audit_terms": ["Planner strategy", "Permission mode"],
        "max_reasoning_steps": 5,
        "workspace_files": {
            "README.md": "# TerminalWorld OpenClaw planner fixture\n",
            "terminalworld_metadata.json": json.dumps({
                "task_id": task_id,
                "terminal_domain": domain,
                "artifact_path": row.get("artifact_path"),
                "requires_docker": row.get("requires_docker"),
                "source_type": row.get("source_type"),
                "pii_status": row.get("pii_status"),
                "license": row.get("license"),
                "complexity": complexity,
                "policy_mode": policy_mode,
            }, ensure_ascii=False, indent=2) + "\n",
        },
        "source_dataset": "EuniAI/TerminalWorld",
        "source_task_uid": task_id,
        "source_family": "terminalworld",
        "terminal_domain": domain,
        "terminalworld_artifact_path": row.get("artifact_path"),
        "terminalworld_requires_docker": row.get("requires_docker"),
        "terminalworld_license": row.get("license"),
        "planner_profile": "terminal_cli_workflow",
        "profile_execution_tools": ["command_runner"],
        "profile_policy_mode": policy_mode,
        "task_complexity": complexity,
    }


def _clean_instruction(text: str) -> str:
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.DOTALL)
    return " ".join(text.split())


def _complexity(text: str) -> str:
    tokens = re.findall(r"[A-Za-z0-9_./:-]+", text)
    command_markers = len(re.findall(r"`[^`]+`", text))
    if len(tokens) >= 110 or command_markers >= 4:
        return "complex"
    if len(tokens) >= 55 or command_markers >= 2:
        return "medium"
    return "simple"


def _policy_mode(instruction: str, domain: str) -> str:
    lower = f"{domain} {instruction}".lower()
    if any(term in lower for term in ["sudo", "ssh", "security", "credential", "authenticate", "token"]):
        return "confirm"
    return "act"


def _required_events(behavior: str) -> list[str]:
    events = ["planning", "permission", "critique", "run_completed"]
    if behavior == "allow":
        events.extend(["tool_call", "tool_result"])
    if behavior == "ask":
        events.append("human_gate")
    return events


def _safe_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return slug[:80] or "unknown"


def _summarize(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "task_count": len(tasks),
        "split_counts": dict(Counter(task["split"] for task in tasks)),
        "domain_counts": dict(sorted(Counter(task["terminal_domain"] for task in tasks).items())),
        "complexity_counts": dict(sorted(Counter(task["task_complexity"] for task in tasks).items())),
        "policy_counts": dict(sorted(Counter(task["profile_policy_mode"] for task in tasks).items())),
        "source_dataset": "EuniAI/TerminalWorld",
    }


if __name__ == "__main__":
    main()
