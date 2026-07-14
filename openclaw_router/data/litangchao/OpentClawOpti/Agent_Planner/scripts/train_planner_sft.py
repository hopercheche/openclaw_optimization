#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import torch
from datasets import load_dataset
from peft import LoraConfig, PeftModel, get_peft_model
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    DataCollatorForLanguageModeling,
    Trainer,
    TrainingArguments,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="LoRA SFT for the Agent_Planner policy model.")
    parser.add_argument("--model", required=True)
    parser.add_argument("--train-file", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--max-steps", type=int, default=1000)
    parser.add_argument("--max-seq-length", type=int, default=2048)
    parser.add_argument("--max-train-samples", type=int, default=50000)
    parser.add_argument("--per-device-train-batch-size", type=int, default=1)
    parser.add_argument("--gradient-accumulation-steps", type=int, default=16)
    parser.add_argument("--learning-rate", type=float, default=2e-4)
    parser.add_argument("--warmup-steps", type=int, default=50)
    parser.add_argument("--logging-steps", type=int, default=10)
    parser.add_argument("--save-steps", type=int, default=200)
    parser.add_argument("--streaming", action="store_true")
    parser.add_argument("--shuffle-buffer", type=int, default=0)
    parser.add_argument("--lora-r", type=int, default=16)
    parser.add_argument("--lora-alpha", type=int, default=32)
    parser.add_argument("--lora-dropout", type=float, default=0.05)
    parser.add_argument(
        "--adapter-init",
        type=Path,
        help="Optional existing LoRA adapter to continue training from.",
    )
    parser.add_argument("--bf16", action="store_true")
    parser.add_argument("--fp16", action="store_true")
    parser.add_argument("--require-cuda", action="store_true")
    args = parser.parse_args()

    _fail_fast_cuda(args.require_cuda)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    _write_run_config(args)

    tokenizer = AutoTokenizer.from_pretrained(
        args.model,
        trust_remote_code=True,
        local_files_only=True,
    )
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    dataset = load_dataset(
        "json",
        data_files={"train": str(args.train_file)},
        split="train",
        streaming=args.streaming,
    )
    if args.streaming:
        if args.shuffle_buffer:
            dataset = dataset.shuffle(buffer_size=args.shuffle_buffer, seed=42)
        if args.max_train_samples:
            dataset = dataset.take(args.max_train_samples)
        train_dataset = dataset
        data_collator = LazyTextCollator(tokenizer, args.max_seq_length)
    else:
        if args.max_train_samples and len(dataset) > args.max_train_samples:
            dataset = dataset.select(range(args.max_train_samples))
        train_dataset = dataset.map(
            lambda batch: _tokenize(batch, tokenizer, args.max_seq_length),
            batched=True,
            remove_columns=dataset.column_names,
            desc="tokenizing planner SFT data",
        )
        data_collator = DataCollatorForLanguageModeling(tokenizer=tokenizer, mlm=False)

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

    if args.adapter_init:
        model = PeftModel.from_pretrained(
            model,
            str(args.adapter_init),
            is_trainable=True,
            local_files_only=True,
        )
    else:
        lora_config = LoraConfig(
            r=args.lora_r,
            lora_alpha=args.lora_alpha,
            lora_dropout=args.lora_dropout,
            bias="none",
            task_type="CAUSAL_LM",
            target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
        )
        model = get_peft_model(model, lora_config)
    model.print_trainable_parameters()

    training_args = TrainingArguments(
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
        dataloader_num_workers=0 if args.streaming else 2,
        dataloader_pin_memory=torch.cuda.is_available(),
        gradient_checkpointing=True,
    )
    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=train_dataset,
        data_collator=data_collator,
    )
    trainer.train()
    trainer.save_model(str(args.output_dir / "final_adapter"))
    tokenizer.save_pretrained(str(args.output_dir / "final_adapter"))


def _fail_fast_cuda(require_cuda: bool) -> None:
    if not require_cuda:
        return
    if not torch.cuda.is_available() or torch.cuda.device_count() < 1:
        raise SystemExit(
            "CUDA is required but no CUDA device is visible. "
            "Check /dev/nvidia* and nvidia-smi before launching training."
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


def _tokenize(batch: dict[str, list[Any]], tokenizer, max_seq_length: int) -> dict[str, list[list[int]]]:
    texts = batch.get("text")
    if texts is None:
        texts = [
            _fallback_text(goal, response)
            for goal, response in zip(batch.get("goal", []), batch.get("response", []), strict=False)
        ]
    tokenized = tokenizer(
        texts,
        truncation=True,
        max_length=max_seq_length,
        padding=False,
    )
    tokenized["labels"] = [ids.copy() for ids in tokenized["input_ids"]]
    return tokenized


class LazyTextCollator:
    def __init__(self, tokenizer, max_seq_length: int) -> None:
        self.tokenizer = tokenizer
        self.max_seq_length = max_seq_length

    def __call__(self, features: list[dict[str, Any]]) -> dict[str, torch.Tensor]:
        texts = []
        for feature in features:
            text = feature.get("text")
            if not isinstance(text, str):
                text = _fallback_text(feature.get("goal"), feature.get("response"))
            texts.append(text)
        batch = self.tokenizer(
            texts,
            truncation=True,
            max_length=self.max_seq_length,
            padding=True,
            return_tensors="pt",
        )
        labels = batch["input_ids"].clone()
        labels[batch["attention_mask"] == 0] = -100
        batch["labels"] = labels
        return batch


def _fallback_text(goal: Any, response: Any) -> str:
    return f"<|im_start|>user\n{goal or ''}<|im_end|>\n<|im_start|>assistant\n{response or ''}<|im_end|>\n"


if __name__ == "__main__":
    main()
