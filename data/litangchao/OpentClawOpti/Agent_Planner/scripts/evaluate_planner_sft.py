#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gc
import json
import math
import re
import statistics
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer


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


@dataclass(slots=True)
class ModelEvalResult:
    label: str
    adapter_path: str | None
    examples_scored: int
    target_tokens_scored: int
    loss: float
    perplexity: float
    generation_examples: int
    valid_json_rate: float
    schema_valid_rate: float
    required_field_rate: float
    command_array_rate: float
    command_overlap_mean: float
    task_complete_bool_rate: float
    mean_ttft_seconds: float
    p50_ttft_seconds: float
    p95_ttft_seconds: float
    mean_generation_seconds: float
    mean_new_tokens: float
    mean_tokens_per_second: float
    gpu_peak_memory_mb: float | None


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate a base planner model against a LoRA adapter.")
    parser.add_argument("--base-model", type=Path, required=True)
    parser.add_argument("--adapter", type=Path, required=True)
    parser.add_argument("--eval-file", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--start-line", type=int, default=300001)
    parser.add_argument("--loss-examples", type=int, default=64)
    parser.add_argument("--generation-examples", type=int, default=16)
    parser.add_argument("--max-seq-length", type=int, default=1024)
    parser.add_argument("--max-new-tokens", type=int, default=256)
    parser.add_argument("--dtype", choices=["bf16", "fp16", "fp32"], default="bf16")
    parser.add_argument("--require-cuda", action="store_true")
    parser.add_argument("--skip-base", action="store_true")
    args = parser.parse_args()

    if args.require_cuda and not torch.cuda.is_available():
        raise SystemExit("CUDA is required for this evaluation, but torch cannot see a CUDA device.")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    examples_needed = max(args.loss_examples, args.generation_examples)
    examples = load_examples(args.eval_file, args.start_line, examples_needed)
    if not examples:
        raise SystemExit(f"No valid examples found in {args.eval_file} starting at line {args.start_line}")

    tokenizer = AutoTokenizer.from_pretrained(
        str(args.base_model),
        trust_remote_code=True,
        local_files_only=True,
    )
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    write_jsonl(args.output_dir / "eval_samples.jsonl", [asdict(example) for example in examples])
    run_config = {
        "created_at": utc_now(),
        "base_model": str(args.base_model),
        "adapter": str(args.adapter),
        "eval_file": str(args.eval_file),
        "output_dir": str(args.output_dir),
        "start_line": args.start_line,
        "loss_examples": args.loss_examples,
        "generation_examples": args.generation_examples,
        "max_seq_length": args.max_seq_length,
        "max_new_tokens": args.max_new_tokens,
        "dtype": args.dtype,
        "require_cuda": args.require_cuda,
        "skip_base": args.skip_base,
        "cuda_available": torch.cuda.is_available(),
        "cuda_device_count": torch.cuda.device_count(),
        "device_name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
    }
    (args.output_dir / "run_config.json").write_text(
        json.dumps(run_config, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    results: list[ModelEvalResult] = []
    generation_rows: list[dict[str, Any]] = []
    model_specs = []
    if not args.skip_base:
        model_specs.append(("base", None))
    model_specs.append(("lora_adapter", args.adapter))

    for label, adapter_path in model_specs:
        result, rows = evaluate_model(
            label=label,
            base_model=args.base_model,
            adapter_path=adapter_path,
            tokenizer=tokenizer,
            examples=examples,
            loss_examples=args.loss_examples,
            generation_examples=args.generation_examples,
            max_seq_length=args.max_seq_length,
            max_new_tokens=args.max_new_tokens,
            dtype=args.dtype,
        )
        results.append(result)
        generation_rows.extend(rows)
        cleanup_cuda()

    metrics = {
        "created_at": utc_now(),
        "run_config": run_config,
        "results": [asdict(result) for result in results],
        "comparison": compare_results(results),
    }
    (args.output_dir / "metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    write_jsonl(args.output_dir / "generations.jsonl", generation_rows)
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


def evaluate_model(
    *,
    label: str,
    base_model: Path,
    adapter_path: Path | None,
    tokenizer,
    examples: list[EvalExample],
    loss_examples: int,
    generation_examples: int,
    max_seq_length: int,
    max_new_tokens: int,
    dtype: str,
) -> tuple[ModelEvalResult, list[dict[str, Any]]]:
    model = load_model(base_model, adapter_path, dtype)
    device = next(model.parameters()).device
    if torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()

    loss, target_tokens = score_loss(
        model,
        tokenizer,
        examples[:loss_examples],
        max_seq_length=max_seq_length,
        device=device,
    )
    generation_metrics, generation_rows = evaluate_generations(
        model,
        tokenizer,
        examples[:generation_examples],
        max_seq_length=max_seq_length,
        max_new_tokens=max_new_tokens,
        device=device,
        label=label,
    )
    peak_memory = (
        round(torch.cuda.max_memory_allocated() / 1024 / 1024, 2)
        if torch.cuda.is_available()
        else None
    )
    result = ModelEvalResult(
        label=label,
        adapter_path=str(adapter_path) if adapter_path else None,
        examples_scored=loss_examples,
        target_tokens_scored=target_tokens,
        loss=round(loss, 6),
        perplexity=round(math.exp(min(loss, 20.0)), 4),
        generation_examples=generation_metrics["generation_examples"],
        valid_json_rate=generation_metrics["valid_json_rate"],
        schema_valid_rate=generation_metrics["schema_valid_rate"],
        required_field_rate=generation_metrics["required_field_rate"],
        command_array_rate=generation_metrics["command_array_rate"],
        command_overlap_mean=generation_metrics["command_overlap_mean"],
        task_complete_bool_rate=generation_metrics["task_complete_bool_rate"],
        mean_ttft_seconds=generation_metrics["mean_ttft_seconds"],
        p50_ttft_seconds=generation_metrics["p50_ttft_seconds"],
        p95_ttft_seconds=generation_metrics["p95_ttft_seconds"],
        mean_generation_seconds=generation_metrics["mean_generation_seconds"],
        mean_new_tokens=generation_metrics["mean_new_tokens"],
        mean_tokens_per_second=generation_metrics["mean_tokens_per_second"],
        gpu_peak_memory_mb=peak_memory,
    )
    del model
    return result, generation_rows


def load_model(base_model: Path, adapter_path: Path | None, dtype: str):
    torch_dtype = {
        "bf16": torch.bfloat16,
        "fp16": torch.float16,
        "fp32": torch.float32,
    }[dtype]
    model = AutoModelForCausalLM.from_pretrained(
        str(base_model),
        torch_dtype=torch_dtype,
        device_map="auto" if torch.cuda.is_available() else None,
        trust_remote_code=True,
        local_files_only=True,
    )
    if adapter_path is not None:
        model = PeftModel.from_pretrained(model, str(adapter_path), local_files_only=True)
    model.eval()
    return model


def score_loss(model, tokenizer, examples: list[EvalExample], *, max_seq_length: int, device) -> tuple[float, int]:
    loss_total = 0.0
    token_total = 0
    for example in examples:
        input_ids, labels = make_lm_example(
            tokenizer,
            example.prompt,
            example.target,
            max_seq_length=max_seq_length,
        )
        if not input_ids or not any(label != -100 for label in labels):
            continue
        input_tensor = torch.tensor([input_ids], dtype=torch.long, device=device)
        labels_tensor = torch.tensor([labels], dtype=torch.long, device=device)
        attention_mask = torch.ones_like(input_tensor, device=device)
        with torch.no_grad():
            output = model(input_ids=input_tensor, attention_mask=attention_mask, labels=labels_tensor)
        target_count = int((labels_tensor != -100).sum().item())
        loss_total += float(output.loss.item()) * target_count
        token_total += target_count
    if token_total == 0:
        return 0.0, 0
    return loss_total / token_total, token_total


def make_lm_example(tokenizer, prompt: str, target: str, *, max_seq_length: int) -> tuple[list[int], list[int]]:
    prompt_ids = tokenizer(prompt, add_special_tokens=False)["input_ids"]
    target_ids = tokenizer(target, add_special_tokens=False)["input_ids"]
    if len(target_ids) >= max_seq_length:
        target_ids = target_ids[: max_seq_length - 1]
        prompt_tail: list[int] = []
    else:
        prompt_budget = max_seq_length - len(target_ids)
        prompt_tail = prompt_ids[-prompt_budget:]
    input_ids = prompt_tail + target_ids
    labels = [-100] * len(prompt_tail) + target_ids
    return input_ids, labels


def evaluate_generations(
    model,
    tokenizer,
    examples: list[EvalExample],
    *,
    max_seq_length: int,
    max_new_tokens: int,
    device,
    label: str,
) -> tuple[dict[str, float | int], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    ttfts: list[float] = []
    generation_seconds: list[float] = []
    new_token_counts: list[int] = []
    valid_json_count = 0
    schema_valid_count = 0
    command_array_count = 0
    task_complete_bool_count = 0
    field_scores: list[float] = []
    command_overlaps: list[float] = []

    for example in examples:
        input_ids = truncate_prompt(tokenizer, example.prompt, max_prompt_tokens=max(1, max_seq_length - 8))
        input_tensor = torch.tensor([input_ids], dtype=torch.long, device=device)
        attention_mask = torch.ones_like(input_tensor, device=device)

        synchronize()
        started = time.perf_counter()
        with torch.no_grad():
            model.generate(
                input_ids=input_tensor,
                attention_mask=attention_mask,
                max_new_tokens=1,
                do_sample=False,
                pad_token_id=tokenizer.pad_token_id,
                eos_token_id=tokenizer.eos_token_id,
            )
        synchronize()
        ttft = time.perf_counter() - started

        synchronize()
        started = time.perf_counter()
        with torch.no_grad():
            output = model.generate(
                input_ids=input_tensor,
                attention_mask=attention_mask,
                max_new_tokens=max_new_tokens,
                do_sample=False,
                pad_token_id=tokenizer.pad_token_id,
                eos_token_id=tokenizer.eos_token_id,
            )
        synchronize()
        elapsed = time.perf_counter() - started
        new_tokens = int(output.shape[-1] - input_tensor.shape[-1])
        generated = tokenizer.decode(output[0, input_tensor.shape[-1]:], skip_special_tokens=False)
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
        ttfts.append(ttft)
        generation_seconds.append(elapsed)
        new_token_counts.append(new_tokens)

        rows.append({
            "model_label": label,
            "line_number": example.line_number,
            "source": example.source,
            "task_preview": example.task_preview,
            "ttft_seconds": round(ttft, 6),
            "generation_seconds": round(elapsed, 6),
            "new_tokens": new_tokens,
            "tokens_per_second": round(new_tokens / max(elapsed, 1e-9), 4),
            "schema": schema,
            "command_overlap": round(command_overlap, 4),
            "expected_commands": sorted(expected_commands),
            "predicted_commands": sorted(predicted_commands),
            "generated_text": generated,
        })

    total = len(examples) or 1
    return {
        "generation_examples": len(examples),
        "valid_json_rate": round(valid_json_count / total, 4),
        "schema_valid_rate": round(schema_valid_count / total, 4),
        "required_field_rate": round(statistics.mean(field_scores) if field_scores else 0.0, 4),
        "command_array_rate": round(command_array_count / total, 4),
        "command_overlap_mean": round(statistics.mean(command_overlaps) if command_overlaps else 0.0, 4),
        "task_complete_bool_rate": round(task_complete_bool_count / total, 4),
        "mean_ttft_seconds": round(statistics.mean(ttfts) if ttfts else 0.0, 6),
        "p50_ttft_seconds": round(percentile(ttfts, 50), 6),
        "p95_ttft_seconds": round(percentile(ttfts, 95), 6),
        "mean_generation_seconds": round(statistics.mean(generation_seconds) if generation_seconds else 0.0, 6),
        "mean_new_tokens": round(statistics.mean(new_token_counts) if new_token_counts else 0.0, 4),
        "mean_tokens_per_second": round(
            statistics.mean(
                tokens / max(seconds, 1e-9)
                for tokens, seconds in zip(new_token_counts, generation_seconds, strict=False)
            )
            if new_token_counts
            else 0.0,
            4,
        ),
    }, rows


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


def compare_results(results: list[ModelEvalResult]) -> dict[str, Any]:
    by_label = {result.label: result for result in results}
    base = by_label.get("base")
    adapter = by_label.get("lora_adapter")
    if base is None or adapter is None:
        return {}
    return {
        "loss_delta_adapter_minus_base": round(adapter.loss - base.loss, 6),
        "loss_relative_change": round((adapter.loss - base.loss) / max(base.loss, 1e-9), 6),
        "valid_json_rate_delta": round(adapter.valid_json_rate - base.valid_json_rate, 4),
        "schema_valid_rate_delta": round(adapter.schema_valid_rate - base.schema_valid_rate, 4),
        "command_overlap_delta": round(adapter.command_overlap_mean - base.command_overlap_mean, 4),
        "mean_ttft_seconds_delta": round(adapter.mean_ttft_seconds - base.mean_ttft_seconds, 6),
        "tokens_per_second_delta": round(adapter.mean_tokens_per_second - base.mean_tokens_per_second, 4),
    }


def render_report(metrics: dict[str, Any]) -> str:
    lines = [
        "# Agent Planner SFT Evaluation",
        "",
        f"- Created at: {metrics['created_at']}",
        f"- Eval file: `{metrics['run_config']['eval_file']}`",
        f"- Start line: {metrics['run_config']['start_line']}",
        f"- Loss examples: {metrics['run_config']['loss_examples']}",
        f"- Generation examples: {metrics['run_config']['generation_examples']}",
        f"- Base model: `{metrics['run_config']['base_model']}`",
        f"- Adapter: `{metrics['run_config']['adapter']}`",
        f"- CUDA available: {metrics['run_config']['cuda_available']}",
        f"- Device: {metrics['run_config']['device_name']}",
        "",
        "## Results",
        "",
        "| Model | Loss | PPL | Valid JSON | Schema valid | Cmd overlap | TTFT mean | Gen tok/s | Peak GPU MB |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for result in metrics["results"]:
        lines.append(
            f"| `{result['label']}` | {result['loss']:.6f} | {result['perplexity']:.4f} | "
            f"{result['valid_json_rate']:.2%} | {result['schema_valid_rate']:.2%} | "
            f"{result['command_overlap_mean']:.4f} | {result['mean_ttft_seconds']:.4f}s | "
            f"{result['mean_tokens_per_second']:.2f} | {result['gpu_peak_memory_mb']} |"
        )
    comparison = metrics.get("comparison") or {}
    if comparison:
        lines.extend([
            "",
            "## Adapter Delta",
            "",
            f"- Loss delta adapter-base: {comparison['loss_delta_adapter_minus_base']}",
            f"- Loss relative change: {comparison['loss_relative_change']:.2%}",
            f"- Valid JSON rate delta: {comparison['valid_json_rate_delta']:.2%}",
            f"- Schema valid rate delta: {comparison['schema_valid_rate_delta']:.2%}",
            f"- Command overlap delta: {comparison['command_overlap_delta']:.4f}",
            f"- Mean TTFT delta: {comparison['mean_ttft_seconds_delta']:.4f}s",
            f"- Tokens/sec delta: {comparison['tokens_per_second_delta']:.4f}",
        ])
    return "\n".join(lines).rstrip() + "\n"


def percentile(values: list[float], percentile_value: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * percentile_value / 100
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[int(rank)]
    weight = rank - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def cleanup_cuda() -> None:
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


def synchronize() -> None:
    if torch.cuda.is_available():
        torch.cuda.synchronize()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    main()
