# Agent Planner SFT Evaluation

- Created at: 2026-06-24T08:20:32.394544Z
- Eval file: `/home/litangchao/OpenClawPOpti/data/litangchao/OpentClawOpti/Agent_Planner/processed/qwen_terminal_toolbench_sft_jsononly_strict_eval_line300001_1k.jsonl`
- Start line: 1
- Loss examples: 64
- Generation examples: 16
- Base model: `/home/litangchao/.cache/huggingface/hub/models--Qwen--Qwen2.5-3B-Instruct/snapshots/aa8e72537993ba99e69dfaafa59ed015b17504d1`
- Adapter: `/home/litangchao/OpenClawPOpti/data/litangchao/OpentClawOpti/Agent_Planner/models/20260624T081500Z-qwen25-3b-gpu1-strict-json-stage3-500/final_adapter`
- CUDA available: True
- Device: NVIDIA L20

## Results

| Model | Loss | PPL | Valid JSON | Schema valid | Cmd overlap | TTFT mean | Gen tok/s | Peak GPU MB |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `base` | 1.715666 | 5.5604 | 87.50% | 6.25% | 0.0037 | 0.0445s | 59.44 | 7753.12 |
| `lora_adapter` | 0.827208 | 2.2869 | 31.25% | 31.25% | 0.1408 | 0.0633s | 27.78 | 7867.31 |

## Adapter Delta

- Loss delta adapter-base: -0.888458
- Loss relative change: -51.79%
- Valid JSON rate delta: -56.25%
- Schema valid rate delta: 25.00%
- Command overlap delta: 0.1371
- Mean TTFT delta: 0.0188s
- Tokens/sec delta: -31.6589
