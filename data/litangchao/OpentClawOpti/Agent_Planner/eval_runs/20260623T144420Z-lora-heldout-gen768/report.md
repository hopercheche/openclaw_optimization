# Agent Planner SFT Evaluation

- Created at: 2026-06-23T14:47:20.968147Z
- Eval file: `/home/litangchao/OpenClawPOpti/data/litangchao/OpentClawOpti/Agent_Planner/processed/qwen_terminal_toolbench_sft.jsonl`
- Start line: 300001
- Loss examples: 0
- Generation examples: 8
- Base model: `/home/litangchao/.cache/huggingface/hub/models--Qwen--Qwen2.5-3B-Instruct/snapshots/aa8e72537993ba99e69dfaafa59ed015b17504d1`
- Adapter: `/home/litangchao/OpenClawPOpti/data/litangchao/OpentClawOpti/Agent_Planner/models/20260623T063028Z-qwen25-3b-gpu1-stream200k-5k/final_adapter`
- CUDA available: True
- Device: NVIDIA L20

## Results

| Model | Loss | PPL | Valid JSON | Schema valid | Cmd overlap | TTFT mean | Gen tok/s | Peak GPU MB |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `lora_adapter` | 0.000000 | 1.0000 | 50.00% | 50.00% | 0.1175 | 0.0966s | 28.28 | 6197.34 |
