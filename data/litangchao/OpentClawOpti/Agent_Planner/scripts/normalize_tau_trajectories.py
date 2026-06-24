#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert tau-bench trajectory JSONL files into reward examples for planner training.",
    )
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit-per-file", type=int, default=0)
    args = parser.parse_args()

    files = sorted(path for path in args.input_dir.glob("*.jsonl") if path.is_file())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    successes = 0
    with args.output.open("w", encoding="utf-8") as handle:
        for path in files:
            for index, row in enumerate(_iter_jsonl(path), start=1):
                if args.limit_per_file and index > args.limit_per_file:
                    break
                example = _to_reward_example(path, row)
                successes += int(example["reward"]["success"])
                total += 1
                handle.write(json.dumps(example, ensure_ascii=False) + "\n")

    print(json.dumps({
        "input_dir": str(args.input_dir),
        "output": str(args.output),
        "source_files": [path.name for path in files],
        "examples": total,
        "successes": successes,
        "success_rate": round(successes / total, 4) if total else 0.0,
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


def _to_reward_example(path: Path, row: dict[str, Any]) -> dict[str, Any]:
    messages = row.get("messages") or []
    eval_result = row.get("eval_result") or {}
    score = float(eval_result.get("score") or 0.0)
    db_match = bool(eval_result.get("db_match"))
    success = score >= 1.0 or db_match
    user_goal = _first_user_message(messages)
    assistant_steps = _assistant_messages(messages)
    tool_events = _tool_events(messages)
    return {
        "source_file": path.name,
        "benchmark_name": row.get("benchmark_name"),
        "task_name": row.get("task_name"),
        "model_path": row.get("model_path"),
        "goal": user_goal,
        "trajectory": {
            "message_count": len(messages),
            "assistant_steps": assistant_steps,
            "tool_events": tool_events,
        },
        "reward": {
            "success": success,
            "score": score,
            "db_match": db_match,
            "invalid_tool": False,
            "policy_violation": False,
            "loop": _has_repeated_assistant_step(assistant_steps),
        },
        "raw_eval_result": eval_result,
    }


def _first_user_message(messages: list[dict[str, Any]]) -> str:
    for message in messages:
        if message.get("role") == "user":
            return _content_text(message)
    return ""


def _assistant_messages(messages: list[dict[str, Any]]) -> list[str]:
    return [
        _content_text(message)
        for message in messages
        if message.get("role") == "assistant" and _content_text(message)
    ]


def _tool_events(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for message in messages:
        if message.get("role") not in {"tool", "function"}:
            continue
        events.append({
            "role": message.get("role"),
            "name": message.get("name") or message.get("tool_name"),
            "content": _content_text(message)[:1000],
        })
    return events


def _content_text(message: dict[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if isinstance(text, str):
                    parts.append(text)
            elif isinstance(item, str):
                parts.append(item)
        return "\n".join(parts)
    return ""


def _has_repeated_assistant_step(steps: list[str]) -> bool:
    normalized = [" ".join(step.split()).lower()[:240] for step in steps if step.strip()]
    return len(normalized) != len(set(normalized))


if __name__ == "__main__":
    main()
