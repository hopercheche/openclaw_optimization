# Agent Planner SFT Evaluation

- Created at: 2026-06-24T08:46:58.158921Z
- Eval file: `/home/litangchao/OpenClawPOpti/data/litangchao/OpentClawOpti/Agent_Planner/processed/qwen_terminal_toolbench_sft_jsononly_strict_action3_eval_line300001_1k.jsonl`
- Start line: 1
- Loss examples: 64
- Generation examples: 16
- Base model: `/home/litangchao/.cache/huggingface/hub/models--Qwen--Qwen2.5-3B-Instruct/snapshots/aa8e72537993ba99e69dfaafa59ed015b17504d1`
- Adapter: `/home/litangchao/OpenClawPOpti/data/litangchao/OpentClawOpti/Agent_Planner/models/20260624T091500Z-qwen25-3b-gpu1-action3-stage4-500/final_adapter`
- CUDA available: True
- Device: NVIDIA L20

## Results

| Model | Loss | PPL | Valid JSON | Schema valid | Cmd overlap | TTFT mean | Gen tok/s | Peak GPU MB |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `base` | 2.252767 | 9.5140 | 87.50% | 6.25% | 0.0037 | 0.0478s | 59.07 | 7753.12 |
| `lora_adapter` | 0.941443 | 2.5637 | 87.50% | 87.50% | 0.2253 | 0.0672s | 28.04 | 7867.31 |

## Adapter Delta

- Loss delta adapter-base: -1.311324
- Loss relative change: -58.21%
- Valid JSON rate delta: 0.00%
- Schema valid rate delta: 81.25%
- Command overlap delta: 0.2216
- Mean TTFT delta: 0.0194s
- Tokens/sec delta: -31.0311
