# Agent Planner SFT Evaluation

- Created at: 2026-06-23T14:40:36.632658Z
- Eval file: `/home/litangchao/OpenClawPOpti/data/litangchao/OpentClawOpti/Agent_Planner/processed/qwen_terminal_toolbench_sft.jsonl`
- Start line: 300001
- Loss examples: 64
- Generation examples: 16
- Base model: `/home/litangchao/.cache/huggingface/hub/models--Qwen--Qwen2.5-3B-Instruct/snapshots/aa8e72537993ba99e69dfaafa59ed015b17504d1`
- Adapter: `/home/litangchao/OpenClawPOpti/data/litangchao/OpentClawOpti/Agent_Planner/models/20260623T063028Z-qwen25-3b-gpu1-stream200k-5k/final_adapter`
- CUDA available: True
- Device: NVIDIA L20

## Results

| Model | Loss | PPL | Valid JSON | Schema valid | Cmd overlap | TTFT mean | Gen tok/s | Peak GPU MB |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `base` | 1.811775 | 6.1213 | 12.50% | 0.00% | 0.1250 | 0.0446s | 60.63 | 7753.41 |
| `lora_adapter` | 1.056539 | 2.8764 | 0.00% | 0.00% | 0.1250 | 0.0619s | 27.88 | 7867.6 |

## Adapter Delta

- Loss delta adapter-base: -0.755236
- Loss relative change: -41.68%
- Valid JSON rate delta: -12.50%
- Schema valid rate delta: 0.00%
- Command overlap delta: 0.0000
- Mean TTFT delta: 0.0173s
- Tokens/sec delta: -32.7495
