#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import statistics
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import torch
import vllm
from transformers import AutoTokenizer
from vllm import LLM, SamplingParams
from vllm.sampling_params import StructuredOutputsParams
from vllm.inputs.data import TokensPrompt


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
    parser = argparse.ArgumentParser(description="Benchmark a merged planner model with vLLM offline generation.")
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--tokenizer", type=Path, default=None)
    parser.add_argument("--eval-file", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--start-line", type=int, default=1)
    parser.add_argument("--generation-examples", type=int, default=64)
    parser.add_argument("--max-model-len", type=int, default=1024)
    parser.add_argument("--max-new-tokens", type=int, default=192)
    parser.add_argument("--prompt-token-budget", type=int, default=None)
    parser.add_argument("--min-new-tokens", type=int, default=0)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--dtype", choices=["auto", "bfloat16", "float16", "float32"], default="bfloat16")
    parser.add_argument("--gpu-memory-utilization", type=float, default=0.45)
    parser.add_argument("--enforce-eager", action="store_true")
    parser.add_argument("--text-prompts", action="store_true")
    parser.add_argument("--ignore-eos", action="store_true")
    parser.add_argument("--suppress-eos", action="store_true")
    parser.add_argument("--structured-json", action="store_true")
    parser.add_argument(
        "--strict-schema",
        action="store_true",
        help="Use additionalProperties=false in the guided JSON schema.",
    )
    parser.add_argument(
        "--require-task-complete",
        action="store_true",
        help="Require task_complete in the guided JSON schema.",
    )
    parser.add_argument("--presence-penalty", type=float, default=0.0)
    parser.add_argument("--frequency-penalty", type=float, default=0.0)
    parser.add_argument("--repetition-penalty", type=float, default=1.0)
    parser.add_argument("--require-cuda", action="store_true")
    args = parser.parse_args()

    if args.require_cuda and not torch.cuda.is_available():
        raise SystemExit("CUDA is required for this benchmark, but torch cannot see a CUDA device.")
    if args.batch_size < 1:
        raise SystemExit("--batch-size must be >= 1")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    examples = load_examples(args.eval_file, args.start_line, args.generation_examples)
    if not examples:
        raise SystemExit(f"No valid examples found in {args.eval_file} starting at line {args.start_line}")

    tokenizer_path = args.tokenizer or args.model
    effective_tokenizer_path = prepare_tokenizer_path(tokenizer_path, args.output_dir)
    tokenizer = AutoTokenizer.from_pretrained(
        str(effective_tokenizer_path),
        trust_remote_code=True,
        local_files_only=True,
        extra_special_tokens={},
    )
    prompt_token_budget = args.prompt_token_budget
    if prompt_token_budget is None:
        prompt_token_budget = args.max_model_len - args.max_new_tokens
    if prompt_token_budget < 1:
        raise SystemExit("--prompt-token-budget or --max-model-len must leave at least one prompt token.")
    if prompt_token_budget + args.max_new_tokens > args.max_model_len:
        raise SystemExit(
            "--prompt-token-budget + --max-new-tokens must be <= --max-model-len for vLLM."
        )
    prompt_token_ids = [
        truncate_prompt_ids(tokenizer, example.prompt, max_prompt_tokens=prompt_token_budget)
        for example in examples
    ]
    prompts = (
        [tokenizer.decode(ids, skip_special_tokens=False) for ids in prompt_token_ids]
        if args.text_prompts
        else [TokensPrompt(prompt_token_ids=ids) for ids in prompt_token_ids]
    )

    run_config = {
        "created_at": utc_now(),
        "model": str(args.model),
        "tokenizer": str(tokenizer_path),
        "effective_tokenizer": str(effective_tokenizer_path),
        "eval_file": str(args.eval_file),
        "output_dir": str(args.output_dir),
        "start_line": args.start_line,
        "generation_examples": len(examples),
        "max_model_len": args.max_model_len,
        "max_new_tokens": args.max_new_tokens,
        "prompt_token_budget": prompt_token_budget,
        "min_new_tokens": args.min_new_tokens,
        "batch_size": args.batch_size,
        "dtype": args.dtype,
        "gpu_memory_utilization": args.gpu_memory_utilization,
        "enforce_eager": args.enforce_eager,
        "text_prompts": args.text_prompts,
        "ignore_eos": args.ignore_eos,
        "suppress_eos": args.suppress_eos,
        "structured_json": args.structured_json,
        "strict_schema": args.strict_schema,
        "require_task_complete": args.require_task_complete,
        "presence_penalty": args.presence_penalty,
        "frequency_penalty": args.frequency_penalty,
        "repetition_penalty": args.repetition_penalty,
        "require_cuda": args.require_cuda,
        "cuda_available": torch.cuda.is_available(),
        "cuda_device_count": torch.cuda.device_count(),
        "device_name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        "torch_version": torch.__version__,
        "torch_cuda": torch.version.cuda,
        "vllm_version": vllm.__version__,
    }
    (args.output_dir / "run_config.json").write_text(
        json.dumps(run_config, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    write_jsonl(args.output_dir / "eval_samples.jsonl", [asdict(example) for example in examples])

    llm = LLM(
        model=str(args.model),
        tokenizer=str(effective_tokenizer_path),
        trust_remote_code=True,
        dtype=args.dtype,
        max_model_len=args.max_model_len,
        gpu_memory_utilization=args.gpu_memory_utilization,
        enforce_eager=args.enforce_eager,
    )
    logit_bias: dict[int, float] | None = None
    if args.suppress_eos:
        stop_ids = {tokenizer.eos_token_id, tokenizer.pad_token_id}
        logit_bias = {int(token_id): -100.0 for token_id in stop_ids if token_id is not None}

    structured_outputs = (
        StructuredOutputsParams(
            json=planner_json_schema(
                strict=args.strict_schema,
                require_task_complete=args.require_task_complete,
            ),
            disable_additional_properties=args.strict_schema,
        )
        if args.structured_json
        else None
    )

    sampling_params = SamplingParams(
        temperature=0.0,
        max_tokens=args.max_new_tokens,
        min_tokens=args.min_new_tokens,
        stop=None if args.ignore_eos else [IM_END],
        ignore_eos=args.ignore_eos,
        presence_penalty=args.presence_penalty,
        frequency_penalty=args.frequency_penalty,
        repetition_penalty=args.repetition_penalty,
        skip_special_tokens=False,
        spaces_between_special_tokens=False,
        logit_bias=logit_bias,
        structured_outputs=structured_outputs,
    )

    rows: list[dict[str, Any]] = []
    batch_seconds: list[float] = []
    new_token_counts: list[int] = []
    valid_json_count = 0
    schema_valid_count = 0
    command_array_count = 0
    task_complete_bool_count = 0
    field_scores: list[float] = []
    command_overlaps: list[float] = []

    benchmark_started = time.perf_counter()
    for start in range(0, len(prompts), args.batch_size):
        batch_prompts = prompts[start:start + args.batch_size]
        batch_examples = examples[start:start + args.batch_size]
        torch.cuda.synchronize() if torch.cuda.is_available() else None
        started = time.perf_counter()
        outputs = llm.generate(batch_prompts, sampling_params, use_tqdm=False)
        torch.cuda.synchronize() if torch.cuda.is_available() else None
        elapsed = time.perf_counter() - started
        batch_seconds.append(elapsed)

        for example, output in zip(batch_examples, outputs, strict=False):
            completion = output.outputs[0]
            generated = completion.text
            token_ids = getattr(completion, "token_ids", None) or []
            new_tokens = len(token_ids)
            finish_reason = getattr(completion, "finish_reason", None)
            stop_reason = getattr(completion, "stop_reason", None)
            parsed = parse_planner_json(generated)
            schema = score_schema(parsed)
            expected_commands = command_tokens(example.expected_json)
            predicted_commands = command_tokens(parsed)
            command_overlap = token_jaccard(expected_commands, predicted_commands)

            valid_json_count += int(parsed is not None)
            schema_valid_count += int(schema["schema_valid"])
            command_array_count += int(schema["commands_valid"])
            task_complete_bool_count += int(schema["task_complete_bool"])
            field_scores.append(schema["required_field_fraction"])
            command_overlaps.append(command_overlap)
            new_token_counts.append(new_tokens)

            rows.append({
                "line_number": example.line_number,
                "source": example.source,
                "task_preview": example.task_preview,
                "batch_size": len(batch_prompts),
                "batch_generation_seconds": round(elapsed, 6),
                "amortized_request_seconds": round(elapsed / max(len(batch_prompts), 1), 6),
                "new_tokens": new_tokens,
                "finish_reason": finish_reason,
                "stop_reason": stop_reason,
                "schema": schema,
                "command_overlap": round(command_overlap, 4),
                "expected_commands": sorted(expected_commands),
                "predicted_commands": sorted(predicted_commands),
                "generated_text": generated,
            })

    total_generation_seconds = time.perf_counter() - benchmark_started
    total_examples = len(examples) or 1
    total_new_tokens = sum(new_token_counts)
    result = {
        "label": f"vllm_batch{args.batch_size}",
        "generation_examples": len(examples),
        "valid_json_rate": round(valid_json_count / total_examples, 4),
        "schema_valid_rate": round(schema_valid_count / total_examples, 4),
        "required_field_rate": round(statistics.mean(field_scores) if field_scores else 0.0, 4),
        "command_array_rate": round(command_array_count / total_examples, 4),
        "command_overlap_mean": round(statistics.mean(command_overlaps) if command_overlaps else 0.0, 4),
        "task_complete_bool_rate": round(task_complete_bool_count / total_examples, 4),
        "total_generation_seconds": round(total_generation_seconds, 6),
        "sum_batch_generation_seconds": round(sum(batch_seconds), 6),
        "mean_batch_generation_seconds": round(statistics.mean(batch_seconds) if batch_seconds else 0.0, 6),
        "mean_amortized_request_seconds": round(sum(batch_seconds) / total_examples, 6),
        "mean_new_tokens": round(statistics.mean(new_token_counts) if new_token_counts else 0.0, 4),
        "total_new_tokens": total_new_tokens,
        "tokens_per_second": round(total_new_tokens / max(sum(batch_seconds), 1e-9), 4),
        "gpu_peak_memory_mb": round(torch.cuda.max_memory_allocated() / 1024 / 1024, 2)
        if torch.cuda.is_available()
        else None,
    }
    metrics = {
        "created_at": utc_now(),
        "run_config": run_config,
        "results": [result],
    }
    (args.output_dir / "metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    write_jsonl(args.output_dir / "generations.jsonl", rows)
    (args.output_dir / "report.md").write_text(render_report(metrics), encoding="utf-8")
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


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


def prepare_tokenizer_path(tokenizer_path: Path, output_dir: Path) -> Path:
    """Create a tiny tokenizer-only copy when newer configs break older serving envs."""
    config_path = tokenizer_path / "tokenizer_config.json"
    if not config_path.exists():
        return tokenizer_path
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(config.get("extra_special_tokens"), list):
        return tokenizer_path

    compat_dir = output_dir / "tokenizer_compat"
    compat_dir.mkdir(parents=True, exist_ok=True)
    for filename in (
        "tokenizer.json",
        "tokenizer_config.json",
        "special_tokens_map.json",
        "added_tokens.json",
        "chat_template.jinja",
    ):
        source = tokenizer_path / filename
        if source.exists():
            shutil.copy2(source, compat_dir / filename)
    config["extra_special_tokens"] = {}
    (compat_dir / "tokenizer_config.json").write_text(
        json.dumps(config, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return compat_dir


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


def truncate_prompt_ids(tokenizer, prompt: str, *, max_prompt_tokens: int) -> list[int]:
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


def planner_json_schema(*, strict: bool = False, require_task_complete: bool = False) -> dict[str, Any]:
    command_schema = {
        "type": "object",
        "properties": {
            "keystrokes": {"type": "string"},
            "duration": {"type": "number"},
        },
        "required": ["keystrokes"],
        "additionalProperties": not strict,
    }
    required = ["analysis", "plan", "commands"]
    if require_task_complete:
        required.append("task_complete")
    return {
        "type": "object",
        "properties": {
            "analysis": {"type": "string"},
            "plan": {"type": "string"},
            "commands": {
                "type": "array",
                "items": command_schema,
            },
            "task_complete": {"type": "boolean"},
        },
        "required": required,
        "additionalProperties": not strict,
    }


def extract_task_preview(prompt: str) -> str:
    marker = "Task Description:"
    index = prompt.find(marker)
    if index >= 0:
        preview = prompt[index + len(marker):]
    else:
        preview = prompt
    preview = re.sub(r"\s+", " ", preview).strip()
    return preview[:300]


def render_report(metrics: dict[str, Any]) -> str:
    config = metrics["run_config"]
    result = metrics["results"][0]
    return "\n".join([
        "# Agent Planner vLLM Benchmark",
        "",
        f"- Created at: {metrics['created_at']}",
        f"- Model: `{config['model']}`",
        f"- Tokenizer: `{config['tokenizer']}`",
        f"- Eval file: `{config['eval_file']}`",
        f"- Generation examples: {config['generation_examples']}",
        f"- Max model len: {config['max_model_len']}",
        f"- Max new tokens: {config['max_new_tokens']}",
        f"- Prompt token budget: {config['prompt_token_budget']}",
        f"- Batch size: {config['batch_size']}",
        f"- Frequency penalty: {config['frequency_penalty']}",
        f"- Repetition penalty: {config['repetition_penalty']}",
        f"- vLLM: {config['vllm_version']}",
        f"- Torch: {config['torch_version']} / CUDA {config['torch_cuda']}",
        f"- Device: {config['device_name']}",
        "",
        "## Results",
        "",
        "| Schema valid | Mean amortized request | Mean tokens | Tok/s | Total gen seconds | Peak GPU MB |",
        "| ---: | ---: | ---: | ---: | ---: | ---: |",
        f"| {result['schema_valid_rate']:.2%} | {result['mean_amortized_request_seconds']:.4f}s | "
        f"{result['mean_new_tokens']:.2f} | {result['tokens_per_second']:.2f} | "
        f"{result['sum_batch_generation_seconds']:.4f}s | {result['gpu_peak_memory_mb']} |",
    ]) + "\n"


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    main()
