# Agent Planner SFT Evaluation

- Created at: 2026-06-24T07:54:27.148840Z
- Eval file: `/home/litangchao/OpenClawPOpti/data/litangchao/OpentClawOpti/Agent_Planner/processed/qwen_terminal_toolbench_sft_jsononly_eval_line300001_1k.jsonl`
- Start line: 1
- Loss examples: 64
- Generation examples: 16
- Base model: `/home/litangchao/.cache/huggingface/hub/models--Qwen--Qwen2.5-3B-Instruct/snapshots/aa8e72537993ba99e69dfaafa59ed015b17504d1`
- Adapter: `/home/litangchao/OpenClawPOpti/data/litangchao/OpentClawOpti/Agent_Planner/models/20260624T070128Z-qwen25-3b-gpu1-jsononly-stage2-1k/final_adapter`
- CUDA available: True
- Device: NVIDIA L20

## Results

| Model | Loss | PPL | Valid JSON | Schema valid | Cmd overlap | TTFT mean | Gen tok/s | Peak GPU MB |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `base` | 1.721292 | 5.5917 | 12.50% | 0.00% | 0.0000 | 0.0424s | 61.41 | 7753.12 |
| `lora_adapter` | 0.811242 | 2.2507 | 31.25% | 31.25% | 0.1272 | 0.0618s | 28.36 | 7867.31 |

## Adapter Delta

- Loss delta adapter-base: -0.91005
- Loss relative change: -52.87%
- Valid JSON rate delta: 18.75%
- Schema valid rate delta: 31.25%
- Command overlap delta: 0.1272
- Mean TTFT delta: 0.0194s
- Tokens/sec delta: -33.0466
