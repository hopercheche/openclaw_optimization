#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import statistics
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from transformers import AutoTokenizer


ASSISTANT_MARKER = "<|im_start|>assistant\n"
IM_END = "<|im_end|>"
REQUIRED_FIELDS = ("analysis", "plan", "commands")


@dataclass(slots=True)
class EvalExample:
    source: str
    line_number: int
    prompt: str
    target: str
    task_preview: str
    expected_json: dict[str, Any] | None


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark planner generation through an HTTP /generate endpoint.")
    parser.add_argument("--endpoint", required=True, help="HTTP generation endpoint, for example http://127.0.0.1:30080/generate")
    parser.add_argument("--tokenizer", type=Path, required=True)
    parser.add_argument("--eval-file", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--start-line", type=int, default=1)
    parser.add_argument("--generation-examples", type=int, default=64)
    parser.add_argument("--prompt-token-budget", type=int, default=1024)
    parser.add_argument("--max-new-tokens", type=int, default=256)
    parser.add_argument("--concurrency", type=int, default=16)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--repetition-penalty", type=float, default=1.0)
    parser.add_argument("--top-p", type=float, default=1.0)
    parser.add_argument("--top-k", type=int, default=-1)
    parser.add_argument("--request-timeout", type=float, default=120.0)
    parser.add_argument("--stop", action="append", default=[IM_END])
    args = parser.parse_args()

    if args.concurrency < 1:
        raise SystemExit("--concurrency must be >= 1")
    args.output_dir.mkdir(parents=True, exist_ok=True)

    examples = load_examples(args.eval_file, args.start_line, args.generation_examples)
    if not examples:
        raise SystemExit(f"No valid examples found in {args.eval_file} starting at line {args.start_line}")

    tokenizer = AutoTokenizer.from_pretrained(
        str(args.tokenizer),
        trust_remote_code=True,
        local_files_only=True,
        extra_special_tokens={},
    )
    prepared = [
        {
            "index": index,
            "example": example,
            "prompt": tokenizer.decode(
                truncate_prompt(tokenizer, example.prompt, max_prompt_tokens=args.prompt_token_budget),
                skip_special_tokens=False,
            ),
        }
        for index, example in enumerate(examples)
    ]

    run_config = {
        "created_at": utc_now(),
        "endpoint": args.endpoint,
        "tokenizer": str(args.tokenizer),
        "eval_file": str(args.eval_file),
        "output_dir": str(args.output_dir),
        "start_line": args.start_line,
        "generation_examples": len(examples),
        "prompt_token_budget": args.prompt_token_budget,
        "max_new_tokens": args.max_new_tokens,
        "concurrency": args.concurrency,
        "temperature": args.temperature,
        "repetition_penalty": args.repetition_penalty,
        "top_p": args.top_p,
        "top_k": args.top_k,
        "request_timeout": args.request_timeout,
        "stop": args.stop,
    }
    (args.output_dir / "run_config.json").write_text(
        json.dumps(run_config, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    write_jsonl(args.output_dir / "eval_samples.jsonl", [asdict(example) for example in examples])

    rows_by_index: dict[int, dict[str, Any]] = {}
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        futures = [
            executor.submit(
                generate_one,
                endpoint=args.endpoint,
                item=item,
                max_new_tokens=args.max_new_tokens,
                temperature=args.temperature,
                repetition_penalty=args.repetition_penalty,
                top_p=args.top_p,
                top_k=args.top_k,
                stop=args.stop,
                timeout=args.request_timeout,
            )
            for item in prepared
        ]
        for future in as_completed(futures):
            row = future.result()
            rows_by_index[row["original_index"]] = row
    total_seconds = time.perf_counter() - started

    rows = [rows_by_index[index] for index in sorted(rows_by_index)]
    metrics = build_metrics(run_config, rows, total_seconds)
    (args.output_dir / "metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    write_jsonl(args.output_dir / "generations.jsonl", rows)
    (args.output_dir / "report.md").write_text(render_report(metrics), encoding="utf-8")
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


def generate_one(
    *,
    endpoint: str,
    item: dict[str, Any],
    max_new_tokens: int,
    temperature: float,
    repetition_penalty: float,
    top_p: float,
    top_k: int,
    stop: list[str],
    timeout: float,
) -> dict[str, Any]:
    example: EvalExample = item["example"]
    payload = {
        "text": item["prompt"],
        "sampling_params": {
            "temperature": temperature,
            "max_new_tokens": max_new_tokens,
            "repetition_penalty": repetition_penalty,
            "top_p": top_p,
            "top_k": top_k,
            "stop": stop,
        },
    }
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response_body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"HTTP generation failed for line {example.line_number}: "
            f"HTTP {exc.code} {exc.reason}: {error_body}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"HTTP generation failed for line {example.line_number}: {exc}") from exc
    elapsed = time.perf_counter() - started

    response_payload = json.loads(response_body)
    generated = str(response_payload.get("text", ""))
    meta_info = response_payload.get("meta_info") if isinstance(response_payload, dict) else None
    output_ids = response_payload.get("output_ids") if isinstance(response_payload, dict) else None
    new_tokens = len(output_ids) if isinstance(output_ids, list) else None
    if isinstance(meta_info, dict) and isinstance(meta_info.get("completion_tokens"), int):
        new_tokens = int(meta_info["completion_tokens"])

    parsed = parse_planner_json(generated)
    schema = score_schema(parsed)
    expected_commands = command_tokens(example.expected_json)
    predicted_commands = command_tokens(parsed)
    command_overlap = token_jaccard(expected_commands, predicted_commands)
    return {
        "original_index": item["index"],
        "line_number": example.line_number,
        "source": example.source,
        "task_preview": example.task_preview,
        "request_seconds": round(elapsed, 6),
        "new_tokens": new_tokens,
        "schema": schema,
        "command_overlap": round(command_overlap, 4),
        "expected_commands": sorted(expected_commands),
        "predicted_commands": sorted(predicted_commands),
        "generated_text": generated,
        "meta_info": meta_info,
    }


def build_metrics(run_config: dict[str, Any], rows: list[dict[str, Any]], total_seconds: float) -> dict[str, Any]:
    total = len(rows) or 1
    request_seconds = [float(row["request_seconds"]) for row in rows]
    token_counts = [int(row["new_tokens"] or 0) for row in rows]
    field_scores = [float(row["schema"]["required_field_fraction"]) for row in rows]
    command_overlaps = [float(row["command_overlap"]) for row in rows]
    schema_valid_count = sum(1 for row in rows if row["schema"]["schema_valid"])
    valid_json_count = sum(1 for row in rows if row["schema"]["valid_json"])
    command_array_count = sum(1 for row in rows if row["schema"]["commands_valid"])
    task_complete_bool_count = sum(1 for row in rows if row["schema"]["task_complete_bool"])
    total_new_tokens = sum(token_counts)
    result = {
        "label": f"http_concurrency{run_config['concurrency']}",
        "generation_examples": len(rows),
        "valid_json_rate": round(valid_json_count / total, 4),
        "schema_valid_rate": round(schema_valid_count / total, 4),
        "required_field_rate": round(statistics.mean(field_scores) if field_scores else 0.0, 4),
        "command_array_rate": round(command_array_count / total, 4),
        "command_overlap_mean": round(statistics.mean(command_overlaps) if command_overlaps else 0.0, 4),
        "task_complete_bool_rate": round(task_complete_bool_count / total, 4),
        "total_wall_seconds": round(total_seconds, 6),
        "mean_request_seconds": round(statistics.mean(request_seconds) if request_seconds else 0.0, 6),
        "mean_amortized_request_seconds": round(total_seconds / total, 6),
        "p50_request_seconds": round(percentile(request_seconds, 50), 6),
        "p95_request_seconds": round(percentile(request_seconds, 95), 6),
        "mean_new_tokens": round(statistics.mean(token_counts) if token_counts else 0.0, 4),
        "total_new_tokens": total_new_tokens,
        "tokens_per_second": round(total_new_tokens / max(total_seconds, 1e-9), 4),
    }
    return {
        "created_at": utc_now(),
        "run_config": run_config,
        "results": [result],
    }


def load_examples(path: Path, start_line: int, limit: int) -> list[EvalExample]:
    examples: list[EvalExample] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if line_number < start_line:
                continue
            payload = json.loads(line)
            text = payload.get("text")
            if not isinstance(text, str):
                continue
            split = split_sft_text(text)
            if split is None:
                continue
            prompt, target = split
            examples.append(
                EvalExample(
                    source=str(payload.get("source", "")),
                    line_number=line_number,
                    prompt=prompt,
                    target=target,
                    task_preview=extract_task_preview(prompt),
                    expected_json=parse_planner_json(target),
                )
            )
            if len(examples) >= limit:
                break
    return examples


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


def truncate_prompt(tokenizer, prompt: str, *, max_prompt_tokens: int) -> list[int]:
    prompt_ids = tokenizer(prompt, add_special_tokens=False)["input_ids"]
    return prompt_ids[-max_prompt_tokens:]


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


def score_schema(parsed: dict[str, Any] | None) -> dict[str, Any]:
    if parsed is None:
        return {
            "valid_json": False,
            "schema_valid": False,
            "required_field_fraction": 0.0,
            "commands_valid": False,
            "task_complete_bool": False,
        }
    fields_present = sum(1 for field in REQUIRED_FIELDS if field in parsed)
    commands = parsed.get("commands")
    commands_valid = isinstance(commands, list) and all(
        isinstance(command, dict)
        and isinstance(command.get("keystrokes"), str)
        and (
            "duration" not in command
            or isinstance(command.get("duration"), int | float)
        )
        for command in commands
    )
    schema_valid = (
        isinstance(parsed.get("analysis"), str)
        and isinstance(parsed.get("plan"), str)
        and commands_valid
    )
    return {
        "valid_json": True,
        "schema_valid": schema_valid,
        "required_field_fraction": round(fields_present / len(REQUIRED_FIELDS), 4),
        "commands_valid": commands_valid,
        "task_complete_bool": isinstance(parsed.get("task_complete"), bool),
    }


def command_tokens(parsed: dict[str, Any] | None) -> set[str]:
    if not parsed or not isinstance(parsed.get("commands"), list):
        return set()
    tokens: set[str] = set()
    for command in parsed["commands"]:
        if not isinstance(command, dict):
            continue
        keystrokes = command.get("keystrokes")
        if not isinstance(keystrokes, str):
            continue
        for token in re.findall(r"[A-Za-z0-9_./-]+", keystrokes.lower()):
            if token not in {"cd", "&&", "||"}:
                tokens.add(token)
    return tokens


def token_jaccard(left: set[str], right: set[str]) -> float:
    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def extract_task_preview(prompt: str) -> str:
    marker = "Task Description:"
    index = prompt.find(marker)
    if index >= 0:
        preview = prompt[index + len(marker):]
    else:
        preview = prompt
    preview = re.sub(r"\s+", " ", preview).strip()
    return preview[:300]


def percentile(values: list[float], percent: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * (percent / 100)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def render_report(metrics: dict[str, Any]) -> str:
    config = metrics["run_config"]
    result = metrics["results"][0]
    return "\n".join([
        "# Agent Planner HTTP Benchmark",
        "",
        f"- Created at: {metrics['created_at']}",
        f"- Endpoint: `{config['endpoint']}`",
        f"- Tokenizer: `{config['tokenizer']}`",
        f"- Eval file: `{config['eval_file']}`",
        f"- Generation examples: {config['generation_examples']}",
        f"- Prompt token budget: {config['prompt_token_budget']}",
        f"- Max new tokens: {config['max_new_tokens']}",
        f"- Concurrency: {config['concurrency']}",
        "",
        "## Results",
        "",
        "| Schema valid | Mean amortized request | Mean request | P95 request | Mean tokens | Tok/s |",
        "| ---: | ---: | ---: | ---: | ---: | ---: |",
        f"| {result['schema_valid_rate']:.2%} | {result['mean_amortized_request_seconds']:.4f}s | "
        f"{result['mean_request_seconds']:.4f}s | {result['p95_request_seconds']:.4f}s | "
        f"{result['mean_new_tokens']:.2f} | {result['tokens_per_second']:.2f} |",
    ]) + "\n"


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    main()
