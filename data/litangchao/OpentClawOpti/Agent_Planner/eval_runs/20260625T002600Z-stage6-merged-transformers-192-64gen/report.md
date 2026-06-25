# Agent Planner SFT Evaluation

- Created at: 2026-06-25T00:28:41.054264Z
- Eval file: `/home/litangchao/OpenClawPOpti/data/litangchao/OpentClawOpti/Agent_Planner/processed/qwen_terminal_toolbench_sft_jsononly_strict_shortcmd120_action2_eval_line300001_1k.jsonl`
- Start line: 1
- Loss examples: 0
- Generation examples: 64
- Base model: `/home/litangchao/OpenClawPOpti/data/litangchao/OpentClawOpti/Agent_Planner/models/20260625T002525Z-qwen25-3b-stage6-merged`
- Adapter: `none`
- Model label: `merged_stage6`
- CUDA available: True
- Device: NVIDIA L20

## Results

| Model | Loss | PPL | Valid JSON | Schema valid | Cmd overlap | TTFT mean | Gen tok/s | Peak GPU MB |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `merged_stage6` | 0.000000 | 1.0000 | 100.00% | 100.00% | 0.1277 | 0.0483s | 60.30 | 6012.04 |
