from __future__ import annotations

import argparse
import ast
import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = PROJECT_ROOT / "benchmarks" / "tasks" / "030_multisource_planner_generalization_suite.json"
DEFAULT_SUMMARY = PROJECT_ROOT / "data" / "external" / "planner_feature_summary.json"
EXTERNAL_ROOT = PROJECT_ROOT / "data" / "external"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a multi-source planner generalization benchmark from external agent datasets.",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--summary-output", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--phoneharness-limit", type=int, default=6)
    parser.add_argument("--tau2-per-domain", type=int, default=4)
    parser.add_argument("--toolbench-limit", type=int, default=8)
    parser.add_argument("--skillsbench-limit", type=int, default=8)
    args = parser.parse_args()

    tasks = build_tasks(
        phoneharness_limit=args.phoneharness_limit,
        tau2_per_domain=args.tau2_per_domain,
        toolbench_limit=args.toolbench_limit,
        skillsbench_limit=args.skillsbench_limit,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(tasks, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    summary = summarize_tasks(tasks)
    args.summary_output.parent.mkdir(parents=True, exist_ok=True)
    args.summary_output.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "output": str(args.output),
        "summary_output": str(args.summary_output),
        "task_count": len(tasks),
        "source_counts": summary["source_counts"],
        "profile_counts": summary["profile_counts"],
        "split_counts": summary["split_counts"],
    }, ensure_ascii=False, indent=2))


def build_tasks(
    phoneharness_limit: int = 6,
    tau2_per_domain: int = 4,
    toolbench_limit: int = 8,
    skillsbench_limit: int = 8,
) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    tasks.extend(_phoneharness_tasks(phoneharness_limit))
    tasks.extend(_tau2_tasks(tau2_per_domain))
    tasks.extend(_toolbench_tasks(toolbench_limit))
    tasks.extend(_skillsbench_tasks(skillsbench_limit))
    for index, task in enumerate(tasks, start=1):
        task["split"] = "holdout" if index % 4 == 0 else "dev"
    return tasks


def _phoneharness_tasks(limit: int) -> list[dict[str, Any]]:
    path = PROJECT_ROOT / "benchmarks" / "tasks" / "020_phoneharness_planner_suite.json"
    if not path.exists():
        return []
    rows = json.loads(path.read_text(encoding="utf-8"))
    selected = _round_robin_by_key(rows, "category", limit)
    tasks: list[dict[str, Any]] = []
    for index, row in enumerate(selected, start=1):
        task = dict(row)
        task["id"] = f"general_phoneharness_{index:03d}_{row['id']}"
        task["category"] = "generalization_phoneharness"
        task["description"] = "PhoneHarness task reused as one source in the generalization suite."
        task["goal"] = _ensure_profile_terms(
            task["goal"],
            source_family="phoneharness",
            planner_profile="mobile_or_mcp_workflow",
        )
        task["source_family"] = "phoneharness"
        task["planner_profile"] = "mobile_or_mcp_workflow"
        task["profile_execution_tools"] = _execution_tools_from_goal(task["goal"])
        task["profile_policy_mode"] = (
            "refuse"
            if task.get("permission_mode") == "DONT_ASK"
            else "confirm"
            if task.get("permission_mode") == "DEFAULT"
            else "act"
        )
        tasks.append(task)
    return tasks


def _tau2_tasks(per_domain: int) -> list[dict[str, Any]]:
    root = EXTERNAL_ROOT / "tau2-bench-data" / "domains"
    sources = {
        "airline": root / "airline" / "tasks.json",
        "retail": root / "retail" / "tasks.json",
        "telecom": root / "telecom" / "tasks_small.json",
    }
    tasks: list[dict[str, Any]] = []
    for domain, path in sources.items():
        if not path.exists():
            continue
        rows = json.loads(path.read_text(encoding="utf-8"))
        selected = _select_tau2_rows(rows, per_domain)
        for local_index, row in enumerate(selected, start=1):
            profile = _tau2_profile(row)
            task = _profile_task(
                task_id=f"general_tau2_{domain}_{local_index:03d}",
                category="generalization_tau2_policy_tool_agent",
                source_family="tau2",
                planner_profile="policy_tool_agent",
                execution_tools=["mcp_tool_runner"],
                policy_mode=profile["policy_mode"],
                prompt=_tau2_prompt(domain, row, profile),
                expected_execution_tools=["mcp_tool_runner"],
                metadata={
                    "source_dataset": "HuggingFaceH4/tau2-bench-data",
                    "source_domain": domain,
                    "source_task_id": str(row.get("id")),
                    "tau2_action_count": profile["action_count"],
                    "tau2_assertion_count": profile["assertion_count"],
                },
            )
            tasks.append(task)
    return tasks


def _toolbench_tasks(limit: int) -> list[dict[str, Any]]:
    path = EXTERNAL_ROOT / "toolbench" / "data" / "rows_000_100.json"
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = [item.get("row", {}) for item in payload.get("rows", [])]
    rows = _round_robin_by_key(rows, "domain", limit)
    tasks: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        api_list = _parse_api_list(str(row.get("api_list", "")))
        api_names = [
            f"{item.get('tool_name', 'tool')}.{item.get('api_name', 'api')}"
            for item in api_list[:4]
            if isinstance(item, dict)
        ]
        prompt = (
            "Multi-source planner profile "
            f"[source_family=toolbench; planner_profile=api_planning; "
            "execution_tool=mcp_tool_runner; policy_mode=act; "
            f"domain={row.get('domain')}; api_count={len(api_list)}]: "
            f"{row.get('query')}"
        )
        task = _profile_task(
            task_id=f"general_toolbench_{index:03d}",
            category="generalization_toolbench_api_planning",
            source_family="toolbench",
            planner_profile="api_planning",
            execution_tools=["mcp_tool_runner"],
            policy_mode="act",
            prompt=prompt,
            expected_execution_tools=["mcp_tool_runner"],
            metadata={
                "source_dataset": "Maurus/ToolBench",
                "source_query_id": str(row.get("query_id")),
                "toolbench_domain": str(row.get("domain")),
                "toolbench_api_count": len(api_list),
                "toolbench_api_names": api_names,
            },
        )
        tasks.append(task)
    return tasks


def _skillsbench_tasks(limit: int) -> list[dict[str, Any]]:
    root = EXTERNAL_ROOT / "skillsbench" / "tasks"
    task_files = sorted(root.glob("*/task.md"))
    tasks: list[dict[str, Any]] = []
    for index, path in enumerate(task_files[:limit], start=1):
        text = path.read_text(encoding="utf-8")
        metadata = _parse_skillsbench_frontmatter(text)
        slug = path.parent.name
        prompt = (
            "Multi-source planner profile "
            f"[source_family=skillsbench; planner_profile=skill_workflow; "
            "execution_tools=file_writer,command_runner; policy_mode=act; "
            f"difficulty={metadata.get('difficulty', 'unknown')}; "
            f"category={metadata.get('category', 'unknown')}; "
            f"task_type={','.join(metadata.get('task_type', []))}]: "
            f"{_skillsbench_prompt(slug, metadata, text)}"
        )
        task = _profile_task(
            task_id=f"general_skillsbench_{index:03d}_{slug}",
            category="generalization_skillsbench_skill_workflow",
            source_family="skillsbench",
            planner_profile="skill_workflow",
            execution_tools=["file_writer", "command_runner"],
            policy_mode="act",
            prompt=prompt,
            expected_execution_tools=["file_writer", "command_runner"],
            metadata={
                "source_dataset": "benchflow/skillsbench",
                "source_task_slug": slug,
                "skillsbench_difficulty": metadata.get("difficulty", ""),
                "skillsbench_category": metadata.get("category", ""),
                "skillsbench_task_type": metadata.get("task_type", []),
                "skillsbench_interface": metadata.get("interface", []),
                "skillsbench_skill_type": metadata.get("skill_type", []),
            },
        )
        tasks.append(task)
    return tasks


def _profile_task(
    task_id: str,
    category: str,
    source_family: str,
    planner_profile: str,
    execution_tools: list[str],
    policy_mode: str,
    prompt: str,
    expected_execution_tools: list[str],
    metadata: dict[str, Any],
) -> dict[str, Any]:
    has_safety = policy_mode in {"refuse", "confirm"} or "safety_guard" in execution_tools
    behavior = {
        "act": "allow",
        "confirm": "ask",
        "refuse": "deny",
    }.get(policy_mode, "allow")
    permission_mode = {
        "act": "ACCEPT_EDITS",
        "confirm": "DEFAULT",
        "refuse": "DONT_ASK",
    }.get(policy_mode, "ACCEPT_EDITS")
    expected_tools = ["risk_model"]
    if has_safety:
        expected_tools.append("safety_guard")
    expected_tools.extend(["planner", *expected_execution_tools[:2], "verifier"])
    required_events = ["planning", "permission", "critique", "run_completed"]
    if behavior == "allow":
        required_events.extend(["tool_call", "tool_result"])
    if behavior == "ask":
        required_events.append("human_gate")

    return {
        "id": task_id,
        "category": category,
        "description": (
            "Multi-source planner generalization task generated from learned "
            "dataset feature profiles."
        ),
        "goal": prompt,
        "permission_mode": permission_mode,
        "expected_tools": expected_tools,
        "forbidden_tools": ["deploy_runner"],
        "expected_permission_behaviors": {
            tool: [behavior] for tool in expected_execution_tools[:2]
        },
        "required_event_types": required_events,
        "required_audit_terms": ["Planner strategy", "Permission mode"],
        "max_reasoning_steps": 5,
        "workspace_files": {
            "README.md": "# Multi-source planner generalization fixture\n",
            "profile_metadata.json": json.dumps({
                "source_family": source_family,
                "planner_profile": planner_profile,
                "execution_tools": execution_tools,
                "policy_mode": policy_mode,
                **metadata,
            }, ensure_ascii=False, indent=2) + "\n",
        },
        "source_family": source_family,
        "planner_profile": planner_profile,
        "profile_execution_tools": execution_tools,
        "profile_policy_mode": policy_mode,
        **metadata,
    }


def _select_tau2_rows(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = {"act": [], "refuse": [], "confirm": []}
    for row in rows:
        profile = _tau2_profile(row)
        if profile["policy_mode"] in buckets:
            buckets[profile["policy_mode"]].append(row)
    selected: list[dict[str, Any]] = []
    for mode in ["refuse", "confirm", "act"]:
        selected.extend(buckets[mode][: max(1, limit // 3)])
    if len(selected) < limit:
        used = {id(item) for item in selected}
        for row in rows:
            if len(selected) >= limit:
                break
            if id(row) not in used:
                selected.append(row)
    return selected[:limit]


def _tau2_profile(row: dict[str, Any]) -> dict[str, int | str]:
    criteria = row.get("evaluation_criteria", {}) or {}
    actions = criteria.get("actions", []) or []
    assertions = criteria.get("nl_assertions", []) or []
    text = json.dumps(row, ensure_ascii=False).lower()
    policy_mode = "act"
    if any(term in text for term in ["refuse", "not possible", "not allowed", "cannot proceed"]):
        policy_mode = "refuse"
    if any(term in text for term in ["confirm", "confirmation", "approval"]):
        policy_mode = "confirm"
    if actions and policy_mode == "refuse":
        policy_mode = "confirm"
    return {
        "policy_mode": policy_mode,
        "action_count": len(actions),
        "assertion_count": len(assertions),
    }


def _tau2_prompt(domain: str, row: dict[str, Any], profile: dict[str, int | str]) -> str:
    instructions = (((row.get("user_scenario") or {}).get("instructions")) or {})
    reason = str(instructions.get("reason_for_call") or "")
    known = str(instructions.get("known_info") or "")
    task_instructions = str(instructions.get("task_instructions") or "")
    return (
        "Multi-source planner profile "
        f"[source_family=tau2; planner_profile=policy_tool_agent; "
        f"execution_tool=mcp_tool_runner; policy_mode={profile['policy_mode']}; "
        f"domain={domain}; action_count={profile['action_count']}]: "
        f"{reason} {known} {task_instructions}"
    ).strip()


def _parse_api_list(raw: str) -> list[dict[str, Any]]:
    try:
        parsed = ast.literal_eval(raw)
    except Exception:
        return []
    if not isinstance(parsed, list):
        return []
    return [item for item in parsed if isinstance(item, dict)]


def _parse_skillsbench_frontmatter(text: str) -> dict[str, Any]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    try:
        end = lines[1:].index("---") + 1
    except ValueError:
        end = min(len(lines), 80)
    frontmatter = lines[1:end]
    metadata: dict[str, Any] = {
        "task_type": [],
        "interface": [],
        "skill_type": [],
        "modality": [],
    }
    active_list: str | None = None
    for line in frontmatter:
        stripped = line.strip()
        if not stripped or stripped == "metadata:":
            continue
        if stripped.endswith(":") and not stripped.startswith("-"):
            key = stripped[:-1]
            active_list = key if key in metadata else None
            continue
        if stripped.startswith("-") and active_list:
            metadata[active_list].append(stripped[1:].strip().strip("'\""))
            continue
        if ":" in stripped:
            key, value = stripped.split(":", 1)
            key = key.strip()
            value = value.strip().strip("'\"")
            if key in {"difficulty", "category", "subcategory"}:
                metadata[key] = value
            active_list = None
    return metadata


def _skillsbench_prompt(slug: str, metadata: dict[str, Any], text: str) -> str:
    content = text.split("---", 2)[-1]
    content = " ".join(content.split())
    if not content:
        content = f"Complete the SkillsBench task {slug}."
    return content[:900]


def _ensure_profile_terms(goal: str, source_family: str, planner_profile: str) -> str:
    if "planner_profile=" in goal and "source_family=" in goal:
        return goal
    return (
        "Multi-source planner profile "
        f"[source_family={source_family}; planner_profile={planner_profile}; "
        f"{_extract_execution_hint(goal)}]: {goal}"
    )


def _extract_execution_hint(goal: str) -> str:
    lower = goal.lower()
    for marker in ["execution_tools=", "execution_tool="]:
        start = lower.find(marker)
        if start >= 0:
            raw_value = goal[start:].split("]", 1)[0].split(";", 1)[0]
            return raw_value
    return "execution_tool=mcp_tool_runner"


def _execution_tools_from_goal(goal: str) -> list[str]:
    lower_goal = goal.lower()
    tools: list[str] = []
    for tool_name in [
        "mcp_tool_runner",
        "mobile_cli_runner",
        "mobile_gui_runner",
        "file_writer",
        "command_runner",
        "deploy_runner",
    ]:
        if tool_name in lower_goal:
            tools.append(tool_name)
    return tools


def _round_robin_by_key(rows: list[dict[str, Any]], key: str, limit: int) -> list[dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        buckets.setdefault(str(row.get(key, "")), []).append(row)
    selected: list[dict[str, Any]] = []
    while len(selected) < limit and buckets:
        for bucket_key in sorted(list(buckets)):
            if len(selected) >= limit:
                break
            bucket = buckets[bucket_key]
            if bucket:
                selected.append(bucket.pop(0))
            if not bucket:
                buckets.pop(bucket_key, None)
    return selected


def summarize_tasks(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    source_counts = Counter(str(task.get("source_family", "")) for task in tasks)
    profile_counts = Counter(str(task.get("planner_profile", "")) for task in tasks)
    policy_counts = Counter(str(task.get("profile_policy_mode", "")) for task in tasks)
    split_counts = Counter(str(task.get("split", "")) for task in tasks)
    execution_counts: Counter[str] = Counter()
    for task in tasks:
        for tool in task.get("profile_execution_tools", []):
            execution_counts[str(tool)] += 1
    return {
        "source_counts": dict(sorted(source_counts.items())),
        "profile_counts": dict(sorted(profile_counts.items())),
        "policy_counts": dict(sorted(policy_counts.items())),
        "execution_tool_counts": dict(sorted(execution_counts.items())),
        "split_counts": dict(sorted(split_counts.items())),
        "feature_method": [
            "Normalize each dataset into source_family, planner_profile, execution_tools, and policy_mode.",
            "Map policy_mode to permission behavior: act->allow, confirm->ask, refuse->deny.",
            "Use the same OpenClaw task schema across mobile workflows, domain-policy tool agents, API planning, and skill workflows.",
            "Keep raw source metadata in profile_metadata.json fixtures for auditability.",
        ],
    }


if __name__ == "__main__":
    main()
