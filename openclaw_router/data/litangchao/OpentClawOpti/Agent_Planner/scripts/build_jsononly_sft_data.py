#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


ASSISTANT_MARKER = "<|im_start|>assistant\n"
IM_END = "<|im_end|>"
STRICT_JSON_HINT = (
    "\n\nPlanner output policy:\n"
    "Return exactly one valid JSON object and nothing else. "
    "Do not include <think>, markdown fences, prose, comments, or text before/after the JSON object.\n"
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert planner SFT text from verbose <think>+JSON targets to compact JSON-only targets.",
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--start-line", type=int, default=1)
    parser.add_argument("--limit", type=int, default=200000)
    parser.add_argument(
        "--max-source-lines",
        type=int,
        default=0,
        help="Stop after this many source lines from start-line; 0 means no explicit read cap.",
    )
    parser.add_argument(
        "--max-target-chars",
        type=int,
        default=4096,
        help="Skip parsed JSON targets longer than this many compact characters; 0 disables filtering.",
    )
    parser.add_argument(
        "--strict-json-prompt",
        action="store_true",
        help="Inject a strict JSON-only policy into the prompt and remove the original extra-text tolerance line.",
    )
    parser.add_argument("--max-commands", type=int, default=0, help="Keep only the first N commands; 0 keeps all.")
    parser.add_argument(
        "--max-command-keystrokes-chars",
        type=int,
        default=0,
        help="Limit each command's keystrokes length; 0 disables.",
    )
    parser.add_argument(
        "--drop-long-commands",
        action="store_true",
        help="Drop commands whose keystrokes exceed --max-command-keystrokes-chars instead of truncating them.",
    )
    parser.add_argument(
        "--skip-empty-commands",
        action="store_true",
        help="Skip rows where command filtering leaves no commands.",
    )
    parser.add_argument("--max-analysis-chars", type=int, default=0, help="Truncate analysis text to N chars; 0 disables.")
    parser.add_argument("--max-plan-chars", type=int, default=0, help="Truncate plan text to N chars; 0 disables.")
    parser.add_argument(
        "--force-incomplete-on-command-truncation",
        action="store_true",
        help="Set task_complete=false when commands are truncated.",
    )
    args = parser.parse_args()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    stats = convert_jsononly(
        input_path=args.input,
        output_path=args.output,
        start_line=args.start_line,
        limit=args.limit,
        max_source_lines=args.max_source_lines,
        max_target_chars=args.max_target_chars,
        strict_json_prompt=args.strict_json_prompt,
        max_commands=args.max_commands,
        max_command_keystrokes_chars=args.max_command_keystrokes_chars,
        drop_long_commands=args.drop_long_commands,
        skip_empty_commands=args.skip_empty_commands,
        max_analysis_chars=args.max_analysis_chars,
        max_plan_chars=args.max_plan_chars,
        force_incomplete_on_command_truncation=args.force_incomplete_on_command_truncation,
    )
    summary_path = args.output.with_suffix(args.output.suffix + ".summary.json")
    summary_path.write_text(
        json.dumps(stats, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(stats, ensure_ascii=False, indent=2))


def convert_jsononly(
    *,
    input_path: Path,
    output_path: Path,
    start_line: int,
    limit: int,
    max_source_lines: int,
    max_target_chars: int,
    strict_json_prompt: bool,
    max_commands: int,
    max_command_keystrokes_chars: int,
    drop_long_commands: bool,
    skip_empty_commands: bool,
    max_analysis_chars: int,
    max_plan_chars: int,
    force_incomplete_on_command_truncation: bool,
) -> dict[str, Any]:
    stats: dict[str, Any] = {
        "input": str(input_path),
        "output": str(output_path),
        "start_line": start_line,
        "limit": limit,
        "max_source_lines": max_source_lines,
        "max_target_chars": max_target_chars,
        "strict_json_prompt": strict_json_prompt,
        "max_commands": max_commands,
        "max_command_keystrokes_chars": max_command_keystrokes_chars,
        "drop_long_commands": drop_long_commands,
        "skip_empty_commands": skip_empty_commands,
        "max_analysis_chars": max_analysis_chars,
        "max_plan_chars": max_plan_chars,
        "force_incomplete_on_command_truncation": force_incomplete_on_command_truncation,
        "read_rows": 0,
        "written_rows": 0,
        "missing_text": 0,
        "missing_assistant_marker": 0,
        "json_parse_failures": 0,
        "target_too_long": 0,
        "command_truncated": 0,
        "command_keystrokes_truncated": 0,
        "long_commands_dropped": 0,
        "empty_commands_skipped": 0,
        "analysis_truncated": 0,
        "plan_truncated": 0,
        "command_count_histogram": {},
    }
    with input_path.open("r", encoding="utf-8") as reader, output_path.open("w", encoding="utf-8") as writer:
        for line_number, line in enumerate(reader, start=1):
            if line_number < start_line:
                continue
            stats["read_rows"] += 1
            if max_source_lines and stats["read_rows"] > max_source_lines:
                break
            payload = json.loads(line)
            text = payload.get("text")
            if not isinstance(text, str):
                stats["missing_text"] += 1
                continue
            split = split_sft_text(text)
            if split is None:
                stats["missing_assistant_marker"] += 1
                continue
            prompt, target = split
            if strict_json_prompt:
                prompt = make_strict_json_prompt(prompt)
            parsed = parse_planner_json(target)
            if parsed is None:
                stats["json_parse_failures"] += 1
                continue
            parsed, compact_stats = compact_planner_target(
                parsed,
                max_commands=max_commands,
                max_command_keystrokes_chars=max_command_keystrokes_chars,
                drop_long_commands=drop_long_commands,
                max_analysis_chars=max_analysis_chars,
                max_plan_chars=max_plan_chars,
                force_incomplete_on_command_truncation=force_incomplete_on_command_truncation,
            )
            stats["command_truncated"] += compact_stats["command_truncated"]
            stats["command_keystrokes_truncated"] += compact_stats["command_keystrokes_truncated"]
            stats["long_commands_dropped"] += compact_stats["long_commands_dropped"]
            stats["analysis_truncated"] += compact_stats["analysis_truncated"]
            stats["plan_truncated"] += compact_stats["plan_truncated"]
            commands = parsed.get("commands")
            if skip_empty_commands and isinstance(commands, list) and not commands:
                stats["empty_commands_skipped"] += 1
                continue
            compact_json = json.dumps(parsed, ensure_ascii=False, separators=(",", ":"))
            if max_target_chars and len(compact_json) > max_target_chars:
                stats["target_too_long"] += 1
                continue
            command_count = len(parsed.get("commands", [])) if isinstance(parsed.get("commands"), list) else 0
            histogram = stats["command_count_histogram"]
            histogram[str(command_count)] = histogram.get(str(command_count), 0) + 1
            row = {
                "source": payload.get("source", ""),
                "source_file": payload.get("source_file", ""),
                "format": "sft_text_json_only",
                "original_line_number": line_number,
                "target_chars": len(compact_json),
                "command_count": command_count,
                "text": f"{prompt}{compact_json}{IM_END}\n",
            }
            writer.write(json.dumps(row, ensure_ascii=False) + "\n")
            stats["written_rows"] += 1
            if stats["written_rows"] >= limit:
                break
    return stats


def split_sft_text(text: str) -> tuple[str, str] | None:
    marker_index = text.rfind(ASSISTANT_MARKER)
    if marker_index < 0:
        return None
    target_start = marker_index + len(ASSISTANT_MARKER)
    prompt = text[:target_start]
    target = text[target_start:]
    if not target.strip():
        return None
    return prompt, target


def make_strict_json_prompt(prompt: str) -> str:
    prompt = prompt.replace(
        "- Extra text before or after the JSON will generate warnings but be tolerated\n",
        "- Return exactly one valid JSON object and no extra text\n",
    )
    marker_index = prompt.rfind(ASSISTANT_MARKER)
    if marker_index < 0:
        return prompt
    return prompt[:marker_index] + STRICT_JSON_HINT + prompt[marker_index:]


def compact_planner_target(
    parsed: dict[str, Any],
    *,
    max_commands: int,
    max_command_keystrokes_chars: int,
    drop_long_commands: bool,
    max_analysis_chars: int,
    max_plan_chars: int,
    force_incomplete_on_command_truncation: bool,
) -> tuple[dict[str, Any], dict[str, int]]:
    compact = dict(parsed)
    stats = {
        "command_truncated": 0,
        "command_keystrokes_truncated": 0,
        "long_commands_dropped": 0,
        "analysis_truncated": 0,
        "plan_truncated": 0,
    }
    if max_analysis_chars and isinstance(compact.get("analysis"), str):
        original = compact["analysis"]
        compact["analysis"] = truncate_text(original, max_analysis_chars)
        stats["analysis_truncated"] = int(compact["analysis"] != original)
    if max_plan_chars and isinstance(compact.get("plan"), str):
        original = compact["plan"]
        compact["plan"] = truncate_text(original, max_plan_chars)
        stats["plan_truncated"] = int(compact["plan"] != original)
    commands = compact.get("commands")
    if max_command_keystrokes_chars and isinstance(commands, list):
        filtered_commands: list[Any] = []
        dropped_or_truncated = False
        for command in commands:
            if not isinstance(command, dict) or not isinstance(command.get("keystrokes"), str):
                filtered_commands.append(command)
                continue
            keystrokes = command["keystrokes"]
            if len(keystrokes) <= max_command_keystrokes_chars:
                filtered_commands.append(command)
                continue
            dropped_or_truncated = True
            if drop_long_commands:
                stats["long_commands_dropped"] += 1
                continue
            updated_command = dict(command)
            updated_command["keystrokes"] = truncate_text(keystrokes, max_command_keystrokes_chars)
            filtered_commands.append(updated_command)
            stats["command_keystrokes_truncated"] += 1
        compact["commands"] = filtered_commands
        commands = filtered_commands
        if dropped_or_truncated and force_incomplete_on_command_truncation:
            compact["task_complete"] = False
    if max_commands and isinstance(commands, list) and len(commands) > max_commands:
        compact["commands"] = commands[:max_commands]
        stats["command_truncated"] = 1
        if force_incomplete_on_command_truncation:
            compact["task_complete"] = False
    return compact, stats


def truncate_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max(0, max_chars - 3)].rstrip() + "..."


def parse_planner_json(text: str) -> dict[str, Any] | None:
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


if __name__ == "__main__":
    main()
