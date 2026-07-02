#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any


MAX_TEXT_CHARS = 2400


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Build Agent-Lightning-style transition JSONL from normalized "
            "tau-bench reward examples."
        ),
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--credit",
        choices=("final", "uniform"),
        default="final",
        help="Reward assignment strategy for transitions in each trajectory.",
    )
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    summary = Counter()
    reward_sum = 0.0

    with args.output.open("w", encoding="utf-8") as handle:
        for example_index, example in enumerate(_iter_jsonl(args.input), start=1):
            if args.limit and example_index > args.limit:
                break
            transitions = _example_to_transitions(example, args.credit)
            summary["episodes"] += 1
            summary["transitions"] += len(transitions)
            if example.get("reward", {}).get("success"):
                summary["successful_episodes"] += 1
            if example.get("reward", {}).get("loop"):
                summary["loop_episodes"] += 1
            for transition in transitions:
                reward_sum += float(transition["reward"])
                handle.write(json.dumps(transition, ensure_ascii=False) + "\n")

    print(json.dumps({
        "input": str(args.input),
        "output": str(args.output),
        "credit": args.credit,
        "episodes": summary["episodes"],
        "transitions": summary["transitions"],
        "successful_episodes": summary["successful_episodes"],
        "loop_episodes": summary["loop_episodes"],
        "reward_sum": round(reward_sum, 6),
        "avg_transitions_per_episode": round(
            summary["transitions"] / summary["episodes"],
            4,
        ) if summary["episodes"] else 0.0,
    }, ensure_ascii=False, indent=2))


def _iter_jsonl(path: Path):
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON in {path}:{line_number}") from exc


def _example_to_transitions(example: dict[str, Any], credit: str) -> list[dict[str, Any]]:
    trajectory = example.get("trajectory") or {}
    assistant_steps = [
        _shorten(step)
        for step in trajectory.get("assistant_steps") or []
        if isinstance(step, str) and step.strip()
    ]
    if not assistant_steps:
        return []

    tool_events = [
        event
        for event in trajectory.get("tool_events") or []
        if isinstance(event, dict)
    ]
    tool_names = sorted({
        str(event.get("name"))
        for event in tool_events
        if event.get("name")
    })
    terminal_reward = _terminal_reward(example)
    per_step_reward = terminal_reward / len(assistant_steps) if credit == "uniform" else 0.0
    episode_id = _episode_id(example)

    transitions: list[dict[str, Any]] = []
    for index, action_text in enumerate(assistant_steps):
        done = index == len(assistant_steps) - 1
        reward = terminal_reward if done and credit == "final" else per_step_reward
        transitions.append({
            "schema": "agent_lightning_transition_v0",
            "episode_id": episode_id,
            "transition_id": f"{episode_id}:{index:04d}",
            "timestep": index,
            "state": {
                "goal": _shorten(str(example.get("goal") or "")),
                "task_name": example.get("task_name"),
                "benchmark_name": example.get("benchmark_name"),
                "available_tools": tool_names,
                "history": {
                    "assistant_steps": assistant_steps[max(0, index - 3):index],
                    "tool_events": _compact_tool_events(tool_events[: index + 1]),
                },
            },
            "action": {
                "type": "assistant_message",
                "content": action_text,
            },
            "reward": reward,
            "done": done,
            "trajectory_reward": terminal_reward,
            "credit_assignment": credit,
            "verifier": {
                "success": bool(example.get("reward", {}).get("success")),
                "score": float(example.get("reward", {}).get("score") or 0.0),
                "db_match": bool(example.get("reward", {}).get("db_match")),
                "invalid_tool": bool(example.get("reward", {}).get("invalid_tool")),
                "policy_violation": bool(example.get("reward", {}).get("policy_violation")),
                "loop": bool(example.get("reward", {}).get("loop")),
            },
            "source": {
                "source_file": example.get("source_file"),
                "model_path": example.get("model_path"),
            },
        })
    return transitions


def _terminal_reward(example: dict[str, Any]) -> float:
    reward = example.get("reward") or {}
    score = float(reward.get("score") or 0.0)
    if reward.get("success"):
        return max(score, 1.0)
    if reward.get("invalid_tool") or reward.get("policy_violation"):
        return min(score, -1.0)
    if reward.get("loop"):
        return min(score, -0.25)
    return score


def _episode_id(example: dict[str, Any]) -> str:
    digest = hashlib.sha1(
        json.dumps({
            "source_file": example.get("source_file"),
            "task_name": example.get("task_name"),
            "model_path": example.get("model_path"),
            "goal": example.get("goal"),
        }, sort_keys=True, ensure_ascii=False).encode("utf-8"),
    ).hexdigest()[:16]
    parts = [
        str(example.get("benchmark_name") or "bench"),
        str(example.get("task_name") or "task"),
        str(example.get("source_file") or "source"),
        digest,
    ]
    return "/".join(part.replace("/", "_") for part in parts)


def _compact_tool_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    compacted: list[dict[str, Any]] = []
    for event in events[-5:]:
        compacted.append({
            "name": event.get("name"),
            "role": event.get("role"),
            "content": _shorten(str(event.get("content") or ""), max_chars=1200),
        })
    return compacted


def _shorten(text: str, max_chars: int = MAX_TEXT_CHARS) -> str:
    text = text.strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 20].rstrip() + "\n...[truncated]"


if __name__ == "__main__":
    main()
