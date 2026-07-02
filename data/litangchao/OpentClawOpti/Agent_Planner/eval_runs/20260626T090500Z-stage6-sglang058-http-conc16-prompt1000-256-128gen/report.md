# Agent Planner HTTP Benchmark

- Created at: 2026-06-26T08:24:28.039508Z
- Endpoint: `http://127.0.0.1:30080/generate`
- Tokenizer: `data/litangchao/OpentClawOpti/Agent_Planner/eval_runs/20260626T084500Z-stage6-vllm-context1280-batch16-textprompt-256-256gen/tokenizer_compat`
- Eval file: `data/litangchao/OpentClawOpti/Agent_Planner/processed/qwen_terminal_toolbench_sft_jsononly_strict_shortcmd120_action2_eval_line300001_1k.jsonl`
- Generation examples: 128
- Prompt token budget: 1000
- Max new tokens: 256
- Concurrency: 16

## Results

| Schema valid | Mean amortized request | Mean request | P95 request | Mean tokens | Tok/s |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 98.44% | 0.1260s | 1.8900s | 3.1906s | 109.87 | 872.10 |
