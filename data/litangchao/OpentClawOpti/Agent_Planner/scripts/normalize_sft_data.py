#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Normalize ToolBench/Qwen tabular data into planner SFT JSONL.",
    )
    parser.add_argument("--input", type=Path, required=True, help="Input file or directory")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--kind",
        choices=["qwen_text", "toolbench"],
        required=True,
    )
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    try:
        import pyarrow.ipc as ipc
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise SystemExit("pyarrow is required. Install it with: .venv/bin/python -m pip install pyarrow") from exc

    files = _input_files(args.input, args.kind)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with args.output.open("w", encoding="utf-8") as handle:
        for file_path in files:
            for row in _iter_rows(file_path, args.kind, ipc, pq):
                example = _normalize_row(row, args.kind, file_path)
                handle.write(json.dumps(example, ensure_ascii=False) + "\n")
                count += 1
                if args.limit and count >= args.limit:
                    print(json.dumps({"output": str(args.output), "examples": count}, indent=2))
                    return
    print(json.dumps({"output": str(args.output), "examples": count}, indent=2))


def _input_files(path: Path, kind: str) -> list[Path]:
    if path.is_file():
        return [path]
    suffix = "*.arrow" if kind == "qwen_text" else "*.parquet"
    return sorted(path.glob(suffix))


def _iter_rows(path: Path, kind: str, ipc, pq):
    if kind == "toolbench":
        parquet_file = pq.ParquetFile(path)
        for batch in parquet_file.iter_batches(batch_size=1000):
            yield from batch.to_pylist()
        return
    with path.open("rb") as handle:
        try:
            reader = ipc.open_file(handle)
            for index in range(reader.num_record_batches):
                yield from reader.get_batch(index).to_pylist()
        except Exception:
            handle.seek(0)
            reader = ipc.open_stream(handle)
            for batch in reader:
                yield from batch.to_pylist()


def _normalize_row(row: dict[str, Any], kind: str, source_path: Path) -> dict[str, Any]:
    if kind == "qwen_text":
        text = str(row.get("text", ""))
        return {
            "source": "qwen_terminal_toolbench_2b_full",
            "source_file": source_path.name,
            "format": "sft_text",
            "text": text,
            "planner_target": {
                "type": "tool_call_or_terminal_action_sequence",
                "from": "chat_template_text",
            },
        }

    prompt = _first_present(row, ["query", "instruction", "question", "input", "prompt", "id"])
    conversations = row.get("conversations") or row.get("messages")
    response = _first_present(row, ["answer", "output", "response", "text"])
    if not response:
        response = _last_assistant_value(conversations)
    return {
        "source": "toolbench_v1",
        "source_file": source_path.name,
        "format": "toolbench_row",
        "goal": prompt,
        "response": response,
        "conversations": conversations,
        "raw": row,
    }


def _first_present(row: dict[str, Any], keys: list[str]) -> str:
    for key in keys:
        value = row.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def _last_assistant_value(conversations: Any) -> str:
    if not isinstance(conversations, dict):
        return ""
    roles = conversations.get("from") or []
    values = conversations.get("value") or []
    if not isinstance(roles, list) or not isinstance(values, list):
        return ""
    for role, value in zip(reversed(roles), reversed(values)):
        if role == "assistant" and isinstance(value, str):
            return value
    return ""


if __name__ == "__main__":
    main()
