# Agent Planner SFT Evaluation

- Created at: 2026-06-24T16:51:06.739151Z
- Eval file: `/home/litangchao/OpenClawPOpti/data/litangchao/OpentClawOpti/Agent_Planner/processed/qwen_terminal_toolbench_sft_jsononly_strict_shortcmd120_action2_eval_line300001_1k.jsonl`
- Start line: 1
- Loss examples: 0
- Generation examples: 64
- Base model: `/home/litangchao/.cache/huggingface/hub/models--Qwen--Qwen2.5-3B-Instruct/snapshots/aa8e72537993ba99e69dfaafa59ed015b17504d1`
- Adapter: `/home/litangchao/OpenClawPOpti/data/litangchao/OpentClawOpti/Agent_Planner/models/20260624T130000Z-qwen25-3b-gpu1-shortcmd120-action2-stage6-500/final_adapter`
- CUDA available: True
- Device: NVIDIA L20

## Results

| Model | Loss | PPL | Valid JSON | Schema valid | Cmd overlap | TTFT mean | Gen tok/s | Peak GPU MB |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `lora_adapter` | 0.000000 | 1.0000 | 96.88% | 96.88% | 0.1487 | 0.0708s | 27.82 | 6197.34 |
