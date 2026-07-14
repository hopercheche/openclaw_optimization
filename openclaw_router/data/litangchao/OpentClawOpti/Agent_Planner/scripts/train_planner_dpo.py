#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import torch
from datasets import load_dataset
from peft import LoraConfig, PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer
from trl import DPOConfig, DPOTrainer


def main() -> None:
    parser = argparse.ArgumentParser(description="LoRA DPO training for Agent_Planner preference pairs.")
    parser.add_argument("--model", required=True)
    parser.add_argument("--train-file", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--max-steps", type=int, default=500)
    parser.add_argument("--max-length", type=int, default=1024)
    parser.add_argument("--max-train-samples", type=int, default=50000)
    parser.add_argument("--per-device-train-batch-size", type=int, default=1)
    parser.add_argument("--gradient-accumulation-steps", type=int, default=8)
    parser.add_argument("--learning-rate", type=float, default=5e-6)
    parser.add_argument("--warmup-steps", type=int, default=25)
    parser.add_argument("--logging-steps", type=int, default=10)
    parser.add_argument("--save-steps", type=int, default=200)
    parser.add_argument("--beta", type=float, default=0.1)
    parser.add_argument("--lora-r", type=int, default=16)
    parser.add_argument("--lora-alpha", type=int, default=32)
    parser.add_argument("--lora-dropout", type=float, default=0.05)
    parser.add_argument(
        "--adapter-init",
        type=Path,
        help="Optional existing LoRA adapter to continue preference training from.",
    )
    parser.add_argument("--bf16", action="store_true")
    parser.add_argument("--fp16", action="store_true")
    parser.add_argument("--require-cuda", action="store_true")
    args = parser.parse_args()

    _fail_fast_cuda(args.require_cuda)
    _validate_args(args)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    _write_run_config(args)

    tokenizer = AutoTokenizer.from_pretrained(
        args.model,
        trust_remote_code=True,
        local_files_only=True,
    )
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "left"

    dataset = load_dataset(
        "json",
        data_files={"train": str(args.train_file)},
        split="train",
    )
    dataset = dataset.filter(_has_preference_columns, desc="filtering preference pairs")
    if args.max_train_samples and len(dataset) > args.max_train_samples:
        dataset = dataset.select(range(args.max_train_samples))
    if len(dataset) == 0:
        raise SystemExit(f"No valid preference rows found in {args.train_file}")

    dtype = torch.bfloat16 if args.bf16 else (torch.float16 if args.fp16 else torch.float32)
    model = AutoModelForCausalLM.from_pretrained(
        args.model,
        torch_dtype=dtype,
        device_map="auto" if torch.cuda.is_available() else None,
        trust_remote_code=True,
        local_files_only=True,
    )
    model.config.use_cache = False
    if hasattr(model, "gradient_checkpointing_enable"):
        model.gradient_checkpointing_enable()

    peft_config = None
    if args.adapter_init:
        model = PeftModel.from_pretrained(
            model,
            str(args.adapter_init),
            is_trainable=True,
            local_files_only=True,
        )
    else:
        peft_config = LoraConfig(
            r=args.lora_r,
            lora_alpha=args.lora_alpha,
            lora_dropout=args.lora_dropout,
            bias="none",
            task_type="CAUSAL_LM",
            target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
        )
    if hasattr(model, "print_trainable_parameters"):
        model.print_trainable_parameters()

    training_args = DPOConfig(
        output_dir=str(args.output_dir),
        max_steps=args.max_steps,
        per_device_train_batch_size=args.per_device_train_batch_size,
        gradient_accumulation_steps=args.gradient_accumulation_steps,
        learning_rate=args.learning_rate,
        warmup_steps=args.warmup_steps,
        logging_steps=args.logging_steps,
        save_steps=args.save_steps,
        save_total_limit=3,
        bf16=args.bf16,
        fp16=args.fp16,
        report_to=[],
        remove_unused_columns=False,
        dataloader_num_workers=0,
        dataloader_pin_memory=torch.cuda.is_available(),
        gradient_checkpointing=True,
        beta=args.beta,
        max_length=args.max_length,
    )
    trainer = DPOTrainer(
        model=model,
        ref_model=None,
        args=training_args,
        train_dataset=dataset,
        processing_class=tokenizer,
        peft_config=peft_config,
    )
    trainer.train()
    trainer.save_model(str(args.output_dir / "final_adapter"))
    tokenizer.save_pretrained(str(args.output_dir / "final_adapter"))


def _validate_args(args: argparse.Namespace) -> None:
    if args.bf16 and args.fp16:
        raise SystemExit("Use only one of --bf16 or --fp16.")
    if args.max_steps < 1:
        raise SystemExit("--max-steps must be >= 1")
    if args.max_length < 128:
        raise SystemExit("--max-length must be >= 128")
    if args.max_train_samples < 1:
        raise SystemExit("--max-train-samples must be >= 1")
    if args.per_device_train_batch_size < 1:
        raise SystemExit("--per-device-train-batch-size must be >= 1")
    if args.gradient_accumulation_steps < 1:
        raise SystemExit("--gradient-accumulation-steps must be >= 1")


def _has_preference_columns(row: dict[str, Any]) -> bool:
    return all(isinstance(row.get(key), str) and row[key].strip() for key in ("prompt", "chosen", "rejected"))


def _fail_fast_cuda(require_cuda: bool) -> None:
    if not require_cuda:
        return
    if not torch.cuda.is_available() or torch.cuda.device_count() < 1:
        raise SystemExit(
            "CUDA is required but no CUDA device is visible. "
            "Run outside the default sandbox when using GPU training."
        )


def _write_run_config(args: argparse.Namespace) -> None:
    config_path = args.output_dir / "run_config.json"
    payload: dict[str, Any] = vars(args).copy()
    payload["train_file"] = str(payload["train_file"])
    payload["output_dir"] = str(payload["output_dir"])
    if payload.get("adapter_init") is not None:
        payload["adapter_init"] = str(payload["adapter_init"])
    payload["cuda_visible_devices"] = os.environ.get("CUDA_VISIBLE_DEVICES")
    payload["torch_cuda_available"] = torch.cuda.is_available()
    payload["torch_cuda_device_count"] = torch.cuda.device_count()
    config_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
