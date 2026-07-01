#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import torch
from transformers import RepetitionPenaltyLogitsProcessor
from transformers import AutoModelForCausalLM, AutoTokenizer, DynamicCache

from evaluate_planner_sft import (
    command_tokens,
    load_examples,
    parse_planner_json,
    score_schema,
    token_jaccard,
    truncate_prompt,
    utc_now,
    write_jsonl,
)
from planner_quality import command_quality_features, summarize_quality_metrics


DEFAULT_TARGET_MODEL = Path(
    "data/litangchao/OpentClawOpti/Agent_Planner/models/"
    "20260627T-stage7-verifier-combined3k-500-merged"
)
DEFAULT_DRAFT_MODEL = Path(
    "data/litangchao/OpentClawOpti/Agent_Planner/models/openclaw_agent_planner/"
    "stage11_dspark_qwen2_planner_smoke/step_1"
)
DEFAULT_EVAL_FILE = Path(
    "data/litangchao/OpentClawOpti/Agent_Planner/processed/"
    "qwen_terminal_toolbench_sft_jsononly_strict_shortcmd120_action2_100k.jsonl"
)
DEFAULT_DEEPSPEC_ROOT = Path(
    "data/litangchao/OpentClawOpti/Agent_Planner/external/DeepSpec"
)
DEFAULT_AGENT_PLANNER_ROOT = Path("data/litangchao/OpentClawOpti/Agent_Planner")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Run an OpenClaw planner heldout benchmark with a Qwen2 DSpark draft "
            "model and Stage7 target-model verification."
        )
    )
    parser.add_argument("--target-model", type=Path, default=DEFAULT_TARGET_MODEL)
    parser.add_argument("--draft-model", type=Path, default=DEFAULT_DRAFT_MODEL)
    parser.add_argument("--eval-file", type=Path, default=DEFAULT_EVAL_FILE)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--deepspec-root", type=Path, default=DEFAULT_DEEPSPEC_ROOT)
    parser.add_argument(
        "--agent-planner-root",
        type=Path,
        default=DEFAULT_AGENT_PLANNER_ROOT,
        help="Path that contains the deepspec_openclaw package.",
    )
    parser.add_argument("--start-line", type=int, default=5001)
    parser.add_argument("--generation-examples", type=int, default=8)
    parser.add_argument("--max-seq-length", type=int, default=1024)
    parser.add_argument("--max-new-tokens", type=int, default=192)
    parser.add_argument("--dtype", choices=["bf16", "fp16", "fp32"], default="bf16")
    parser.add_argument("--attn-implementation", choices=["eager", "sdpa"], default="sdpa")
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument(
        "--repetition-penalty",
        type=float,
        default=None,
        help=(
            "Target-side greedy repetition penalty. Defaults to the target "
            "model generation_config value so this benchmark matches the "
            "existing Transformers baseline."
        ),
    )
    parser.add_argument("--confidence-threshold", type=float, default=0.0)
    parser.add_argument(
        "--accept-margin",
        type=float,
        default=0.0,
        help=(
            "Conservative greedy-verify margin. A draft token is accepted only "
            "when it equals the target argmax and target top1-top2 logit margin "
            "is at least this value."
        ),
    )
    parser.add_argument(
        "--verify-mode",
        choices=["block", "sequential"],
        default="block",
        help=(
            "Use block target verification for speed probing, or sequential "
            "target verification for exact acceptance diagnostics."
        ),
    )
    parser.add_argument("--compare-target-greedy", action="store_true")
    parser.add_argument("--require-cuda", action="store_true")
    args = parser.parse_args()

    if args.require_cuda and not torch.cuda.is_available():
        raise SystemExit("CUDA is required, but torch cannot see a CUDA device.")
    if args.generation_examples < 1:
        raise SystemExit("--generation-examples must be >= 1")
    if args.max_new_tokens < 1:
        raise SystemExit("--max-new-tokens must be >= 1")
    if args.max_seq_length < 16:
        raise SystemExit("--max-seq-length must be >= 16")

    add_import_paths(args.deepspec_root, args.agent_planner_root)
    from deepspec.eval.base_evaluator import assert_no_final_target_layer  # type: ignore
    from deepspec.eval.dspark.draft_ops import (  # type: ignore
        build_dspark_proposal,
        forward_dspark_draft_block,
    )
    from deepspec.modeling.dspark.common import extract_context_feature  # type: ignore
    from deepspec_openclaw.modeling.dspark.qwen2 import Qwen2DSparkModel

    args.output_dir.mkdir(parents=True, exist_ok=True)
    examples = load_examples(
        args.eval_file,
        args.start_line,
        args.generation_examples,
    )
    if not examples:
        raise SystemExit(f"No valid examples found in {args.eval_file}.")

    torch_dtype = resolve_dtype(args.dtype)
    tokenizer = AutoTokenizer.from_pretrained(
        str(args.target_model),
        trust_remote_code=True,
        local_files_only=True,
    )
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    target_model = AutoModelForCausalLM.from_pretrained(
        str(args.target_model),
        torch_dtype=torch_dtype,
        attn_implementation=args.attn_implementation,
        trust_remote_code=True,
        local_files_only=True,
    ).to(device=device).eval()
    draft_model = Qwen2DSparkModel.from_pretrained(
        str(args.draft_model),
        torch_dtype=torch_dtype,
        attn_implementation=args.attn_implementation,
        local_files_only=True,
    ).to(device=device).eval()
    assert_no_final_target_layer(target_model, draft_model.target_layer_ids)
    stop_token_ids = resolve_stop_token_ids(tokenizer)
    repetition_penalty = (
        float(args.repetition_penalty)
        if args.repetition_penalty is not None
        else float(getattr(target_model.generation_config, "repetition_penalty", 1.0) or 1.0)
    )

    if torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()

    run_config = {
        "created_at": utc_now(),
        "target_model": str(args.target_model),
        "draft_model": str(args.draft_model),
        "eval_file": str(args.eval_file),
        "output_dir": str(args.output_dir),
        "deepspec_root": str(args.deepspec_root),
        "agent_planner_root": str(args.agent_planner_root),
        "start_line": args.start_line,
        "generation_examples": len(examples),
        "max_seq_length": args.max_seq_length,
        "max_new_tokens": args.max_new_tokens,
        "dtype": args.dtype,
        "attn_implementation": args.attn_implementation,
        "temperature": args.temperature,
        "repetition_penalty": repetition_penalty,
        "confidence_threshold": args.confidence_threshold,
        "accept_margin": args.accept_margin,
        "verify_mode": args.verify_mode,
        "compare_target_greedy": args.compare_target_greedy,
        "draft_block_size": int(draft_model.block_size),
        "draft_target_layer_ids": [int(layer_id) for layer_id in draft_model.target_layer_ids],
        "draft_num_hidden_layers": int(draft_model.config.num_hidden_layers),
        "draft_mask_token_id": int(draft_model.mask_token_id),
        "stop_token_ids": stop_token_ids,
        "require_cuda": args.require_cuda,
        "cuda_available": torch.cuda.is_available(),
        "cuda_device_count": torch.cuda.device_count(),
        "device_name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        "torch_version": torch.__version__,
        "torch_cuda": torch.version.cuda,
    }
    (args.output_dir / "run_config.json").write_text(
        json.dumps(run_config, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    write_jsonl(args.output_dir / "eval_samples.jsonl", [asdict(example) for example in examples])

    rows: list[dict[str, Any]] = []
    benchmark_started = time.perf_counter()
    for original_index, example in enumerate(examples):
        prompt_ids = truncate_prompt(
            tokenizer,
            example.prompt,
            max_prompt_tokens=max(1, args.max_seq_length - 8),
        )
        input_ids = torch.tensor([prompt_ids], dtype=torch.long, device=device)
        synchronize()
        started = time.perf_counter()
        with torch.inference_mode():
            response = generate_planner_speculative_sample(
                target_model=target_model,
                input_ids=input_ids,
                max_new_tokens=args.max_new_tokens,
                max_proposal_tokens=int(draft_model.block_size),
                stop_token_ids=stop_token_ids,
                repetition_penalty=repetition_penalty,
                accept_margin=float(args.accept_margin),
                verify_mode=args.verify_mode,
                init_context=lambda initial_output, **kwargs: SimpleNamespace(
                    past_key_values_draft=DynamicCache(),
                    target_hidden_states=extract_context_feature(
                        initial_output.hidden_states,
                        draft_model.target_layer_ids,
                    ),
                ),
                propose=lambda context, output_ids, position_ids, start, stop_token_ids=None: propose_dspark(
                    draft_model=draft_model,
                    context=context,
                    output_ids=output_ids,
                    position_ids=position_ids,
                    start=start,
                    temperature=float(args.temperature),
                    confidence_threshold=float(args.confidence_threshold),
                    forward_dspark_draft_block=forward_dspark_draft_block,
                    build_dspark_proposal=build_dspark_proposal,
                ),
                update=lambda context, verification: update_dspark_context(
                    context=context,
                    verification=verification,
                    draft_model=draft_model,
                    extract_context_feature=extract_context_feature,
                ),
            )
        synchronize()
        elapsed = time.perf_counter() - started
        new_ids = response.output_ids[0, len(prompt_ids):].tolist()
        new_ids = trim_after_stop(new_ids, stop_token_ids=stop_token_ids)
        generated = tokenizer.decode(new_ids, skip_special_tokens=False)

        target_match = None
        target_text = None
        target_seconds = None
        if args.compare_target_greedy:
            synchronize()
            target_started = time.perf_counter()
            with torch.inference_mode():
                baseline_output = target_model.generate(
                    input_ids=input_ids,
                    attention_mask=torch.ones_like(input_ids),
                    max_new_tokens=args.max_new_tokens,
                    do_sample=False,
                    pad_token_id=tokenizer.pad_token_id,
                    eos_token_id=tokenizer.eos_token_id,
                )
            synchronize()
            target_seconds = time.perf_counter() - target_started
            target_new_ids = baseline_output[0, input_ids.shape[-1]:].tolist()
            target_new_ids = trim_after_stop(target_new_ids, stop_token_ids=stop_token_ids)
            target_text = tokenizer.decode(target_new_ids, skip_special_tokens=False)
            target_match = generated == target_text

        rows.append(build_row(
            example=example,
            original_index=original_index,
            prompt_tokens=len(prompt_ids),
            generated=generated,
            elapsed=elapsed,
            response=response,
            target_match=target_match,
            target_text=target_text,
            target_seconds=target_seconds,
        ))

    total_generation_seconds = time.perf_counter() - benchmark_started
    result = summarize_rows(
        rows,
        total_examples=len(examples),
        total_generation_seconds=total_generation_seconds,
        block_size=int(draft_model.block_size),
    )
    metrics = {
        "created_at": utc_now(),
        "run_config": run_config,
        "result": result,
    }
    (args.output_dir / "metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    write_jsonl(args.output_dir / "generations.jsonl", rows)
    (args.output_dir / "report.md").write_text(render_report(metrics), encoding="utf-8")
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


def add_import_paths(deepspec_root: Path, agent_planner_root: Path) -> None:
    for path in (agent_planner_root, deepspec_root):
        resolved = str(path.resolve())
        if resolved not in sys.path:
            sys.path.insert(0, resolved)


def resolve_dtype(dtype: str) -> torch.dtype:
    return {
        "bf16": torch.bfloat16,
        "fp16": torch.float16,
        "fp32": torch.float32,
    }[dtype]


def resolve_stop_token_ids(tokenizer) -> list[int]:
    ids: list[int] = []
    for token_id in (tokenizer.eos_token_id, tokenizer.convert_tokens_to_ids("<|im_end|>")):
        if isinstance(token_id, int) and token_id >= 0 and token_id not in ids:
            ids.append(token_id)
    return ids


def propose_dspark(
    *,
    draft_model,
    context: SimpleNamespace,
    output_ids: torch.Tensor,
    position_ids: torch.Tensor,
    start: int,
    temperature: float,
    confidence_threshold: float,
    forward_dspark_draft_block,
    build_dspark_proposal,
):
    block_size = int(draft_model.block_size)
    draft_input_ids = torch.full(
        (output_ids.size(0), block_size),
        int(draft_model.mask_token_id),
        dtype=torch.long,
        device=output_ids.device,
    )
    draft_input_ids[:, 0] = output_ids[:, start]
    block_hidden = forward_dspark_draft_block(
        draft_model,
        draft_input_ids=draft_input_ids,
        position_ids=position_ids,
        past_key_values_draft=context.past_key_values_draft,
        target_hidden_states=context.target_hidden_states,
        start=start,
        block_size=block_size,
    )
    return build_dspark_proposal(
        model=draft_model,
        draft_input_ids=draft_input_ids,
        block_hidden=block_hidden,
        block_size=block_size,
        temperature=temperature,
        confidence_threshold=confidence_threshold,
    )


@torch.inference_mode()
def generate_planner_speculative_sample(
    *,
    target_model,
    input_ids: torch.Tensor,
    max_new_tokens: int,
    max_proposal_tokens: int,
    stop_token_ids: list[int],
    repetition_penalty: float,
    accept_margin: float,
    verify_mode: str,
    init_context,
    propose,
    update,
) -> SimpleNamespace:
    assert input_ids.size(0) == 1, "only batch_size=1 is supported"
    device = input_ids.device
    num_input_tokens = input_ids.shape[1]
    max_length = num_input_tokens + int(max_new_tokens)
    output_ids = torch.empty(
        (1, max_length + max_proposal_tokens + 1),
        dtype=torch.long,
        device=device,
    )
    position_ids = torch.arange(output_ids.shape[1], device=device).unsqueeze(0)
    past_key_values_target = DynamicCache()

    output = target_model(
        input_ids=input_ids,
        attention_mask=torch.ones(
            (1, num_input_tokens),
            dtype=torch.long,
            device=device,
        ),
        past_key_values=past_key_values_target,
        use_cache=True,
        output_hidden_states=True,
        logits_to_keep=1,
        cache_position=torch.arange(num_input_tokens, device=device),
    )
    output_ids[:, :num_input_tokens] = input_ids
    first_logits = apply_repetition_penalty(
        output.logits[:, -1, :],
        input_ids,
        repetition_penalty,
    )
    output_ids[:, num_input_tokens] = torch.argmax(first_logits, dim=-1)

    start = num_input_tokens
    acceptance_lengths: list[int] = []
    proposal_lengths: list[int] = []
    accepted_draft_lengths: list[int] = []
    if has_stop_token(output_ids[:, start : start + 1], stop_token_ids):
        trimmed = trim_output_ids(output_ids[:, : start + 1], num_input_tokens, stop_token_ids)
        return build_response(
            output_ids=trimmed,
            num_input_tokens=num_input_tokens,
            acceptance_lengths=acceptance_lengths,
            proposal_lengths=proposal_lengths,
            accepted_draft_lengths=accepted_draft_lengths,
        )

    context = init_context(
        initial_output=output,
        output_ids=output_ids,
        position_ids=position_ids,
        num_input_tokens=num_input_tokens,
    )
    while start < max_length:
        proposal = propose(
            context=context,
            output_ids=output_ids,
            position_ids=position_ids,
            start=start,
            stop_token_ids=stop_token_ids,
        )
        verification = verify_planner_draft_tokens(
            target_model=target_model,
            proposal=proposal,
            output_ids=output_ids,
            position_ids=position_ids,
            start=start,
            past_key_values_target=past_key_values_target,
            max_proposal_tokens=max_proposal_tokens,
            repetition_penalty=repetition_penalty,
            accept_margin=accept_margin,
            verify_mode=verify_mode,
            stop_token_ids=stop_token_ids,
        )
        proposal_lengths.append(int(verification.effective_proposal_length))
        accepted_draft_tokens = int(verification.accepted_draft_tokens)
        accepted_draft_lengths.append(accepted_draft_tokens)
        output_ids[:, start : start + accepted_draft_tokens + 1] = (
            proposal.verify_input_ids[:, : accepted_draft_tokens + 1]
        )
        if verification.terminated_by_stop_token:
            acceptance_lengths.append(accepted_draft_tokens)
            start += accepted_draft_tokens
            past_key_values_target.crop(start)
            break

        output_ids[:, start + accepted_draft_tokens + 1] = verification.next_token
        new_token_ids = output_ids[:, start + 1 : start + accepted_draft_tokens + 2]
        acceptance_lengths.append(accepted_draft_tokens + 1)
        start += accepted_draft_tokens + 1
        past_key_values_target.crop(start)
        update(context, verification)
        if has_stop_token(new_token_ids, stop_token_ids):
            break

    output_ids = output_ids[:, : min(start + 1, max_length)]
    output_ids = trim_output_ids(output_ids, num_input_tokens, stop_token_ids)
    return build_response(
        output_ids=output_ids,
        num_input_tokens=num_input_tokens,
        acceptance_lengths=acceptance_lengths,
        proposal_lengths=proposal_lengths,
        accepted_draft_lengths=accepted_draft_lengths,
    )


def verify_planner_draft_tokens(
    *,
    target_model,
    proposal,
    output_ids: torch.Tensor,
    position_ids: torch.Tensor,
    start: int,
    past_key_values_target: DynamicCache,
    max_proposal_tokens: int,
    repetition_penalty: float,
    accept_margin: float,
    verify_mode: str,
    stop_token_ids: list[int],
) -> SimpleNamespace:
    if int(proposal.draft_token_count) > max_proposal_tokens:
        raise ValueError("draft_token_count exceeds max_proposal_tokens")
    if not torch.equal(proposal.verify_input_ids[:, :1], output_ids[:, start : start + 1]):
        raise ValueError("proposal must start with the current accepted token")
    if verify_mode == "sequential":
        return verify_planner_draft_tokens_sequential(
            target_model=target_model,
            proposal=proposal,
            output_ids=output_ids,
            start=start,
            past_key_values_target=past_key_values_target,
            repetition_penalty=repetition_penalty,
            accept_margin=accept_margin,
            stop_token_ids=stop_token_ids,
        )

    draft_token_count = int(proposal.draft_token_count)
    verify_length = draft_token_count + 1
    target_output = target_model(
        input_ids=proposal.verify_input_ids,
        attention_mask=build_block_causal_mask(
            query_length=verify_length,
            past_length=start,
            device=proposal.verify_input_ids.device,
            dtype=next(target_model.parameters()).dtype,
        ),
        past_key_values=past_key_values_target,
        use_cache=True,
        output_hidden_states=True,
        cache_position=torch.arange(
            start,
            start + verify_length,
            device=proposal.verify_input_ids.device,
        ),
    )
    proposed_tokens = proposal.verify_input_ids[:, 1:]
    accepted_draft_tokens = 0
    for offset in range(draft_token_count):
        prefix = torch.cat(
            [output_ids[:, : start + 1], proposed_tokens[:, :offset]],
            dim=1,
        )
        logits = apply_repetition_penalty(
            target_output.logits[:, offset, :],
            prefix,
            repetition_penalty,
        )
        top_values, top_indices = torch.topk(logits, k=2, dim=-1)
        target_token = top_indices[:, 0]
        target_margin = top_values[:, 0] - top_values[:, 1]
        if not torch.equal(target_token, proposed_tokens[:, offset]):
            break
        if float(target_margin.min().item()) < float(accept_margin):
            break
        accepted_draft_tokens += 1

    effective_proposal_length = draft_token_count
    terminated_by_stop_token = False
    if accepted_draft_tokens > 0 and stop_token_ids:
        accepted_slice = proposal.verify_input_ids[0, 1 : accepted_draft_tokens + 1]
        stop_tensor = torch.tensor(
            stop_token_ids,
            dtype=accepted_slice.dtype,
            device=accepted_slice.device,
        )
        eos_hits = torch.isin(accepted_slice, stop_tensor).nonzero(as_tuple=True)[0]
        if eos_hits.numel() > 0:
            eos_pos = int(eos_hits[0].item())
            accepted_draft_tokens = eos_pos + 1
            effective_proposal_length = eos_pos + 1
            terminated_by_stop_token = True

    if terminated_by_stop_token:
        next_token = proposal.verify_input_ids[:, accepted_draft_tokens]
    else:
        next_logits_index = accepted_draft_tokens if accepted_draft_tokens < draft_token_count else -1
        next_prefix = torch.cat(
            [output_ids[:, : start + 1], proposed_tokens[:, :accepted_draft_tokens]],
            dim=1,
        )
        next_logits = apply_repetition_penalty(
            target_output.logits[:, next_logits_index, :],
            next_prefix,
            repetition_penalty,
        )
        next_token = torch.argmax(next_logits, dim=-1)

    committed_tokens = torch.cat(
        [
            proposal.verify_input_ids[:, 1 : accepted_draft_tokens + 1],
            next_token.unsqueeze(1),
        ],
        dim=1,
    )
    return SimpleNamespace(
        target_output=target_output,
        accepted_draft_tokens=accepted_draft_tokens,
        next_token=next_token,
        effective_proposal_length=effective_proposal_length,
        terminated_by_stop_token=terminated_by_stop_token,
        committed_tokens=committed_tokens,
    )


def verify_planner_draft_tokens_sequential(
    *,
    target_model,
    proposal,
    output_ids: torch.Tensor,
    start: int,
    past_key_values_target: DynamicCache,
    repetition_penalty: float,
    accept_margin: float,
    stop_token_ids: list[int],
) -> SimpleNamespace:
    draft_token_count = int(proposal.draft_token_count)
    proposed_tokens = proposal.verify_input_ids[:, 1:]
    hidden_steps: list[tuple[torch.Tensor, ...]] = []

    def forward_one(token_ids: torch.Tensor, position: int) -> torch.Tensor:
        step_output = target_model(
            input_ids=token_ids,
            attention_mask=torch.ones(
                (1, int(position) + 1),
                dtype=torch.long,
                device=token_ids.device,
            ),
            past_key_values=past_key_values_target,
            use_cache=True,
            output_hidden_states=True,
            logits_to_keep=1,
            cache_position=torch.tensor([int(position)], device=token_ids.device),
        )
        hidden_steps.append(tuple(step_output.hidden_states))
        return step_output.logits[:, -1, :]

    last_logits = forward_one(proposal.verify_input_ids[:, :1], start)
    accepted_draft_tokens = 0
    terminated_by_stop_token = False
    for offset in range(draft_token_count):
        prefix = torch.cat(
            [output_ids[:, : start + 1], proposed_tokens[:, :offset]],
            dim=1,
        )
        logits = apply_repetition_penalty(last_logits, prefix, repetition_penalty)
        top_values, top_indices = torch.topk(logits, k=2, dim=-1)
        target_token = top_indices[:, 0]
        target_margin = top_values[:, 0] - top_values[:, 1]
        if not torch.equal(target_token, proposed_tokens[:, offset]):
            break
        if float(target_margin.min().item()) < float(accept_margin):
            break
        accepted_draft_tokens += 1
        if has_stop_token(proposed_tokens[:, offset : offset + 1], stop_token_ids):
            terminated_by_stop_token = True
            break
        last_logits = forward_one(
            proposed_tokens[:, offset : offset + 1],
            start + accepted_draft_tokens,
        )

    effective_proposal_length = (
        accepted_draft_tokens if terminated_by_stop_token else draft_token_count
    )
    if terminated_by_stop_token:
        next_token = proposed_tokens[:, accepted_draft_tokens - 1]
    else:
        next_prefix = torch.cat(
            [output_ids[:, : start + 1], proposed_tokens[:, :accepted_draft_tokens]],
            dim=1,
        )
        next_logits = apply_repetition_penalty(
            last_logits,
            next_prefix,
            repetition_penalty,
        )
        next_token = torch.argmax(next_logits, dim=-1)

    return SimpleNamespace(
        target_output=build_hidden_state_output(hidden_steps),
        accepted_draft_tokens=accepted_draft_tokens,
        next_token=next_token,
        effective_proposal_length=effective_proposal_length,
        terminated_by_stop_token=terminated_by_stop_token,
        committed_tokens=torch.cat(
            [
                proposal.verify_input_ids[:, 1 : accepted_draft_tokens + 1],
                next_token.unsqueeze(1),
            ],
            dim=1,
        ),
    )


def build_hidden_state_output(hidden_steps: list[tuple[torch.Tensor, ...]]) -> SimpleNamespace:
    if not hidden_steps:
        raise ValueError("hidden_steps must not be empty")
    layer_count = len(hidden_steps[0])
    return SimpleNamespace(
        hidden_states=tuple(
            torch.cat([step[layer_idx] for step in hidden_steps], dim=1)
            for layer_idx in range(layer_count)
        )
    )


def build_block_causal_mask(
    *,
    query_length: int,
    past_length: int,
    device: torch.device,
    dtype: torch.dtype,
) -> torch.Tensor:
    key_length = int(past_length) + int(query_length)
    query_positions = torch.arange(query_length, device=device).unsqueeze(1)
    key_positions = torch.arange(key_length, device=device).unsqueeze(0)
    allowed = key_positions <= (int(past_length) + query_positions)
    mask = torch.zeros((query_length, key_length), dtype=dtype, device=device)
    mask = mask.masked_fill(~allowed, torch.finfo(dtype).min)
    return mask.unsqueeze(0).unsqueeze(0)


def apply_repetition_penalty(
    logits: torch.Tensor,
    previous_token_ids: torch.Tensor,
    penalty: float,
) -> torch.Tensor:
    if penalty is None or abs(float(penalty) - 1.0) < 1e-8:
        return logits
    return RepetitionPenaltyLogitsProcessor(float(penalty))(previous_token_ids, logits)


def has_stop_token(token_ids: torch.Tensor, stop_token_ids: list[int]) -> bool:
    if not stop_token_ids:
        return False
    stop_tensor = torch.tensor(stop_token_ids, dtype=token_ids.dtype, device=token_ids.device)
    return bool(torch.isin(token_ids, stop_tensor).any().item())


def trim_output_ids(
    output_ids: torch.Tensor,
    num_input_tokens: int,
    stop_token_ids: list[int],
) -> torch.Tensor:
    if not stop_token_ids:
        return output_ids
    new_ids = output_ids[0, num_input_tokens:]
    stop_tensor = torch.tensor(stop_token_ids, dtype=new_ids.dtype, device=new_ids.device)
    hits = torch.isin(new_ids, stop_tensor).nonzero(as_tuple=True)[0]
    if hits.numel() == 0:
        return output_ids
    end = num_input_tokens + int(hits[0].item()) + 1
    return output_ids[:, :end]


def build_response(
    *,
    output_ids: torch.Tensor,
    num_input_tokens: int,
    acceptance_lengths: list[int],
    proposal_lengths: list[int],
    accepted_draft_lengths: list[int],
) -> SimpleNamespace:
    return SimpleNamespace(
        output_ids=output_ids,
        num_input_tokens=num_input_tokens,
        num_output_tokens=output_ids.shape[1] - num_input_tokens,
        acceptance_lengths=acceptance_lengths,
        proposal_lengths=proposal_lengths,
        accepted_draft_lengths=accepted_draft_lengths,
        verify_count=len(proposal_lengths),
    )


def update_dspark_context(
    *,
    context: SimpleNamespace,
    verification,
    draft_model,
    extract_context_feature,
) -> None:
    verified_target_hidden = extract_context_feature(
        verification.target_output.hidden_states,
        draft_model.target_layer_ids,
    )
    context.target_hidden_states = verified_target_hidden[
        :,
        : verification.accepted_draft_tokens + 1,
        :,
    ]


def build_row(
    *,
    example,
    original_index: int,
    prompt_tokens: int,
    generated: str,
    elapsed: float,
    response,
    target_match: bool | None,
    target_text: str | None,
    target_seconds: float | None,
) -> dict[str, Any]:
    parsed = parse_planner_json(generated)
    schema = score_schema(parsed)
    command_quality = command_quality_features(parsed, schema=schema)
    expected_commands = command_tokens(example.expected_json)
    predicted_commands = command_tokens(parsed)
    command_overlap = token_jaccard(expected_commands, predicted_commands)
    proposal_lengths = [int(value) for value in getattr(response, "proposal_lengths", [])]
    acceptance_lengths = [int(value) for value in getattr(response, "acceptance_lengths", [])]
    accepted_draft_lengths = [
        int(value) for value in getattr(response, "accepted_draft_lengths", [])
    ]
    proposal_count = len(proposal_lengths)
    proposal_token_sum = sum(proposal_lengths)
    accepted_draft_sum = sum(accepted_draft_lengths)
    acceptance_length_sum = sum(acceptance_lengths)
    return {
        "original_index": original_index,
        "line_number": example.line_number,
        "source": example.source,
        "task_preview": example.task_preview,
        "prompt_tokens": prompt_tokens,
        "generation_seconds": round(elapsed, 6),
        "new_tokens": int(getattr(response, "num_output_tokens", 0)),
        "tokens_per_second": round(
            int(getattr(response, "num_output_tokens", 0)) / max(elapsed, 1e-9),
            4,
        ),
        "verify_count": int(getattr(response, "verify_count", proposal_count)),
        "proposal_count": proposal_count,
        "proposal_token_sum": proposal_token_sum,
        "accepted_draft_token_sum": accepted_draft_sum,
        "acceptance_length_sum": acceptance_length_sum,
        "draft_tokens_per_proposal": round(
            proposal_token_sum / max(proposal_count, 1),
            4,
        ),
        "accepted_draft_tokens_per_proposal": round(
            accepted_draft_sum / max(proposal_count, 1),
            4,
        ),
        "verify_rate": round(
            acceptance_length_sum / max(proposal_token_sum + proposal_count, 1),
            4,
        ),
        "proposal_lengths": proposal_lengths,
        "acceptance_lengths": acceptance_lengths,
        "accepted_draft_lengths": accepted_draft_lengths,
        "schema": schema,
        "command_quality": command_quality,
        "command_overlap": round(command_overlap, 4),
        "expected_commands": sorted(expected_commands),
        "predicted_commands": sorted(predicted_commands),
        "target_greedy_exact_match": target_match,
        "target_greedy_seconds": round(target_seconds, 6) if target_seconds is not None else None,
        "target_greedy_generated_text": target_text,
        "generated_text": generated,
    }


def summarize_rows(
    rows: list[dict[str, Any]],
    *,
    total_examples: int,
    total_generation_seconds: float,
    block_size: int,
) -> dict[str, Any]:
    field_scores = [row["schema"]["required_field_fraction"] for row in rows]
    command_overlaps = [row["command_overlap"] for row in rows]
    generation_seconds = [row["generation_seconds"] for row in rows]
    new_token_counts = [row["new_tokens"] for row in rows]
    proposal_counts = [row["proposal_count"] for row in rows]
    verify_counts = [row["verify_count"] for row in rows]
    quality = summarize_quality_metrics(rows)
    position_counts = [0] * block_size
    accepted_counts = [0] * block_size
    for row in rows:
        for proposal_len, accepted_len in zip(
            row["proposal_lengths"],
            row["accepted_draft_lengths"],
        ):
            for pos in range(block_size):
                if proposal_len > pos:
                    position_counts[pos] += 1
                if accepted_len > pos:
                    accepted_counts[pos] += 1
    target_matches = [
        bool(row["target_greedy_exact_match"])
        for row in rows
        if row["target_greedy_exact_match"] is not None
    ]
    target_seconds = [
        row["target_greedy_seconds"]
        for row in rows
        if row["target_greedy_seconds"] is not None
    ]
    total_new_tokens = sum(new_token_counts)
    total_proposal_tokens = sum(row["proposal_token_sum"] for row in rows)
    total_acceptance_length = sum(row["acceptance_length_sum"] for row in rows)
    total_proposals = sum(proposal_counts)
    return {
        "label": "dspark_qwen2_speculative",
        "generation_examples": len(rows),
        "valid_json_rate": round(
            sum(1 for row in rows if row["schema"]["valid_json"]) / total_examples,
            4,
        ),
        "schema_valid_rate": round(
            sum(1 for row in rows if row["schema"]["schema_valid"]) / total_examples,
            4,
        ),
        "required_field_rate": round(statistics.mean(field_scores) if field_scores else 0.0, 4),
        "command_array_rate": round(
            sum(1 for row in rows if row["schema"]["commands_valid"]) / total_examples,
            4,
        ),
        "command_overlap_mean": round(statistics.mean(command_overlaps) if command_overlaps else 0.0, 4),
        "long_command_rate": quality["long_command_rate"],
        "multiline_command_rate": quality["multiline_command_rate"],
        "script_like_command_rate": quality["script_like_command_rate"],
        "risky_command_rate": quality["risky_command_rate"],
        "validation_only_command_rate": quality["validation_only_command_rate"],
        "complete_with_commands_rate": quality["complete_with_commands_rate"],
        "incomplete_without_commands_rate": quality["incomplete_without_commands_rate"],
        "mean_max_command_chars": quality["mean_max_command_chars"],
        "p95_max_command_chars": quality["p95_max_command_chars"],
        "task_complete_bool_rate": round(
            sum(1 for row in rows if row["schema"]["task_complete_bool"]) / total_examples,
            4,
        ),
        "total_generation_seconds": round(total_generation_seconds, 6),
        "sum_generation_seconds": round(sum(generation_seconds), 6),
        "mean_amortized_request_seconds": round(sum(generation_seconds) / total_examples, 6),
        "mean_new_tokens": round(statistics.mean(new_token_counts) if new_token_counts else 0.0, 4),
        "total_new_tokens": total_new_tokens,
        "tokens_per_second": round(total_new_tokens / max(sum(generation_seconds), 1e-9), 4),
        "mean_verify_count": round(statistics.mean(verify_counts) if verify_counts else 0.0, 4),
        "mean_proposal_count": round(statistics.mean(proposal_counts) if proposal_counts else 0.0, 4),
        "draft_tokens_per_proposal": round(
            total_proposal_tokens / max(total_proposals, 1),
            4,
        ),
        "verify_rate": round(
            total_acceptance_length / max(total_proposal_tokens + total_proposals, 1),
            4,
        ),
        "accept_rates_by_position": [
            round(accepted / count, 4) if count else None
            for accepted, count in zip(accepted_counts, position_counts)
        ],
        "target_greedy_exact_match_rate": (
            round(sum(target_matches) / len(target_matches), 4) if target_matches else None
        ),
        "mean_target_greedy_seconds": (
            round(statistics.mean(target_seconds), 6) if target_seconds else None
        ),
        "gpu_peak_memory_mb": round(torch.cuda.max_memory_allocated() / 1024 / 1024, 2)
        if torch.cuda.is_available()
        else None,
    }


def trim_after_stop(new_ids: list[int], *, stop_token_ids: list[int]) -> list[int]:
    if not stop_token_ids:
        return new_ids
    trimmed: list[int] = []
    stops = set(stop_token_ids)
    for token_id in new_ids:
        trimmed.append(int(token_id))
        if int(token_id) in stops:
            break
    return trimmed


def render_report(metrics: dict[str, Any]) -> str:
    config = metrics["run_config"]
    result = metrics["result"]
    match_rate = result["target_greedy_exact_match_rate"]
    return "\n".join([
        "# Agent Planner DSpark Speculative Benchmark",
        "",
        f"- Created at: {metrics['created_at']}",
        f"- Target model: `{config['target_model']}`",
        f"- Draft model: `{config['draft_model']}`",
        f"- Eval file: `{config['eval_file']}`",
        f"- Start line: {config['start_line']}",
        f"- Generation examples: {config['generation_examples']}",
        f"- Max new tokens: {config['max_new_tokens']}",
        f"- Draft block size: {config['draft_block_size']}",
        f"- Confidence threshold: {config['confidence_threshold']}",
        f"- Compare target greedy: {config['compare_target_greedy']}",
        f"- Device: {config['device_name']}",
        "",
        "## Results",
        "",
        "| Schema valid | Mean request | Command overlap | Long cmd | Script-like | Verify rate | Draft/proposal | Mean verifies | Target exact |",
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        f"| {result['schema_valid_rate']:.2%} | "
        f"{result['mean_amortized_request_seconds']:.4f}s | "
        f"{result['command_overlap_mean']:.4f} | "
        f"{result['long_command_rate']:.2%} | "
        f"{result['script_like_command_rate']:.2%} | "
        f"{result['verify_rate']:.4f} | "
        f"{result['draft_tokens_per_proposal']:.2f} | "
        f"{result['mean_verify_count']:.2f} | "
        f"{match_rate:.2%} |" if match_rate is not None else
        f"| {result['schema_valid_rate']:.2%} | "
        f"{result['mean_amortized_request_seconds']:.4f}s | "
        f"{result['command_overlap_mean']:.4f} | "
        f"{result['long_command_rate']:.2%} | "
        f"{result['script_like_command_rate']:.2%} | "
        f"{result['verify_rate']:.4f} | "
        f"{result['draft_tokens_per_proposal']:.2f} | "
        f"{result['mean_verify_count']:.2f} | n/a |",
        "",
        "## Acceptance",
        "",
        f"- Accept rates by draft position: `{result['accept_rates_by_position']}`",
        f"- Mean new tokens: {result['mean_new_tokens']:.2f}",
        f"- Tokens/s: {result['tokens_per_second']:.2f}",
        f"- GPU peak memory: {result['gpu_peak_memory_mb']}",
    ]) + "\n"


def synchronize() -> None:
    if torch.cuda.is_available():
        torch.cuda.synchronize()


if __name__ == "__main__":
    main()
