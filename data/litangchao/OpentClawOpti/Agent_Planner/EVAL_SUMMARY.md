# Agent Planner Evaluation Summary

Updated: 2026-06-26

## Large SFT Run

```text
run: 20260623T063028Z-qwen25-3b-gpu1-stream200k-5k
base: Qwen2.5-3B-Instruct local cache
adapter: models/20260623T063028Z-qwen25-3b-gpu1-stream200k-5k/final_adapter
train_file: processed/qwen_terminal_toolbench_sft.jsonl
samples: 200,000 streaming examples
steps: 5,000 / 5,000
runtime: about 3:31:31
last logged loss at step 5000: 0.3573
```

## Heldout SFT Evaluation

Heldout slice starts at line 300001 of `processed/qwen_terminal_toolbench_sft.jsonl`, outside the first 200k streaming training window.

```text
eval_run: eval_runs/20260623T143655Z-base-vs-lora-heldout
loss_examples: 64
generation_examples: 16
max_new_tokens: 256
gpu: GPU1 / NVIDIA L20
```

| Model | Loss | PPL | Valid JSON | Schema Valid | Mean TTFT | Gen tok/s |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| base | 1.811775 | 6.1213 | 12.50% | 0.00% | 0.0446s | 60.63 |
| LoRA adapter | 1.056539 | 2.8764 | 0.00% | 0.00% | 0.0619s | 27.88 |

Adapter loss improved by 41.68% relative to base, which shows the SFT run learned the heldout token distribution. However, with a 256-token generation budget the adapter often starts with a long `<think>` block and truncates before a complete JSON object.

Adapter-only long-window check:

```text
eval_run: eval_runs/20260623T144420Z-lora-heldout-gen768
generation_examples: 8
max_new_tokens: 768
valid_json_rate: 50.00%
schema_valid_rate: 50.00%
mean_ttft: 0.0966s
mean_generation_seconds: 21.6793s
mean_tokens_per_second: 28.28
```

Conclusion: this adapter is a useful warm-start checkpoint, but it is not yet a fast-response production planner. The next training pass should convert targets to concise JSON-only planner actions, remove or mask `<think>` spans, and evaluate strict schema validity as a first-class metric.

## JSON-Only Optimization Pass

The first LoRA checkpoint was continued through three GPU1 passes:

```text
stage2: JSON-only targets, 200k source rows, 1,000 steps
stage3: strict JSON prompt targets, 100k source rows, 500 steps
stage4: strict JSON prompt + at most 3 commands + shorter action fields, 100k source rows, 500 steps
stage5: stage4 continued on short-command targets, dropping commands with keystrokes longer than 160 chars, 100k source rows, 500 steps
stage6: stage5 continued on compact action2 targets, dropping commands with keystrokes longer than 120 chars, 100k source rows, 500 steps
```

Current recommended adapter:

```text
models/20260624T130000Z-qwen25-3b-gpu1-shortcmd120-action2-stage6-500/final_adapter
```

### Stage Comparison

All rows below use heldout data generated from line 300001 of the original Qwen Terminal ToolBench SFT file. Stage2-4 use the action-level target surface; stage5-6 use progressively shorter command/action target surfaces.

| Run | Eval | Max New Tokens | Gen Examples | Schema Valid | Mean TTFT | Mean Gen Time | Mean Tokens | Gen tok/s |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| stage2 JSON-only | `20260624T080900Z-jsononly-stage2-heldout` | 256 | 16 | 31.25% | 0.0618s | 7.9832s | 226.56 | 28.36 |
| stage3 strict prompt | `20260624T084200Z-strict-json-stage3-heldout` | 256 | 16 | 31.25% | 0.0633s | n/a | 218.69 | 27.78 |
| stage4 action3 | `20260624T101000Z-action3-stage4-heldout` | 256 | 16 | 87.50% | 0.0672s | 7.1978s | 202.00 | 28.04 |
| stage4 action3, wider check | `20260624T103100Z-action3-stage4-heldout-64gen` | 256 | 64 | 76.56% | 0.0767s | 7.2388s | 204.22 | 28.20 |
| stage4 action3, short budget | `20260624T102000Z-action3-stage4-heldout-192` | 192 | 16 | 43.75% | 0.0828s | 6.2234s | 177.31 | 28.48 |
| stage5 shortcmd160 | `20260624T114000Z-shortcmd160-stage5-heldout-64gen` | 256 | 64 | 96.88% | 0.0703s | 5.7663s | 164.28 | 28.49 |
| stage5 shortcmd160, short budget | `20260624T115000Z-shortcmd160-stage5-heldout-192-64gen` | 192 | 64 | 87.50% | 0.0708s | 5.6561s | 159.63 | 28.22 |
| stage6 shortcmd120 action2 | `20260624T133000Z-shortcmd120-action2-stage6-heldout-192-64gen` | 192 | 64 | 96.88% | 0.0708s | 4.6234s | 128.66 | 27.82 |
| stage6 shortcmd120 action2, short budget | `20260624T134000Z-shortcmd120-action2-stage6-heldout-160-64gen` | 160 | 64 | 93.75% | 0.0704s | 4.5087s | 127.11 | 28.19 |
| stage6 merged full model | `20260625T002600Z-stage6-merged-transformers-192-64gen` | 192 | 64 | 100.00% | 0.0483s | 2.1153s | 127.58 | 60.30 |
| stage6 merged Transformers batch8 | `20260625T034500Z-stage6-transformers-batch8-192-64gen` | 192 | 64 | 100.00% | n/a | 0.7403s amortized | 127.59 | 172.35 |
| stage6 merged Transformers batch16 | `20260625T035000Z-stage6-transformers-batch16-192-64gen` | 192 | 64 | 100.00% | n/a | 0.4462s amortized | 123.97 | 277.85 |
| stage6 merged Transformers batch32 | `20260625T035500Z-stage6-transformers-batch32-192-64gen` | 192 | 64 | 98.44% | n/a | 0.6790s amortized | 124.22 | 182.94 |
| stage6 merged Transformers batch16, 256-example baseline | `20260625T054500Z-stage6-transformers-batch16-192-256gen` | 192 | 256 | 100.00% | n/a | 0.3621s amortized | 125.93 | 347.79 |
| stage6 merged Transformers batch16, sorted prompts | `20260625T055000Z-stage6-transformers-batch16-256-sort-256gen` | 256 | 256 | 100.00% | n/a | 0.2638s amortized | 126.90 | 481.10 |
| stage6 merged Transformers batch16, seq768 sorted speed candidate | `20260625T055500Z-stage6-transformers-batch16-256-seq768-sort-256gen` | 256 | 256 | 100.00% | n/a | 0.2420s amortized | 125.67 | 519.25 |
| stage6 merged Transformers batch16, 224-token sorted negative check | `20260626T093000Z-stage6-transformers-batch16-224-sort-256gen` | 224 | 256 | 99.61% | n/a | 0.2634s amortized | 126.89 | 481.76 |
| stage6 merged Transformers batch32, sorted prompts | `20260626T093500Z-stage6-transformers-batch32-256-sort-256gen` | 256 | 256 | 100.00% | n/a | 0.2173s amortized | 125.52 | 577.51 |
| stage6 merged Transformers batch48, sorted prompts | `20260626T100000Z-stage6-transformers-batch48-256-sort-256gen` | 256 | 256 | 100.00% | n/a | 0.2324s amortized | 126.32 | 543.62 |
| stage6 merged Transformers batch64, sorted prompts | `20260626T094000Z-stage6-transformers-batch64-256-sort-256gen` | 256 | 256 | 100.00% | n/a | 0.2244s amortized | 127.23 | 566.87 |
| stage6 merged Transformers batch32, seq960 sorted negative check | `20260626T100500Z-stage6-transformers-batch32-256-seq960-sort-256gen` | 256 | 256 | 100.00% | n/a | 0.2176s amortized | 125.84 | 578.28 |
| stage6 merged Transformers batch32, SDPA/CUDA 512-example fast check | `20260626T102500Z-stage6-transformers-batch32-256-sort-sdpa-cuda-512gen` | 256 | 512 | 99.61% | n/a | 0.2187s amortized | 126.25 | 577.34 |
| stage6 merged Transformers batch16, SDPA/CUDA 512-example fallback check | `20260626T103000Z-stage6-transformers-batch16-256-sort-sdpa-cuda-512gen` | 256 | 512 | 99.80% | n/a | 0.2541s amortized | 126.88 | 499.25 |
| stage6 merged Transformers batch32, compact policy 320-token 512-example check | `20260626T104000Z-stage6-transformers-batch32-320-sort-sdpa-cuda-clamp-512gen` | 320 | 512 | 100.00% | n/a | 0.2298s amortized | 135.25 | 588.63 |
| stage6 merged vLLM batch1 | `20260625T010100Z-stage6-vllm-batch1-192-64gen` | 192 | 64 | 59.38% | n/a | 0.6635s amortized | 63.42 | 95.58 |
| stage6 merged vLLM batch8 | `20260625T010800Z-stage6-vllm-batch8-192-64gen` | 192 | 64 | 60.94% | n/a | 0.2157s amortized | 65.23 | 302.50 |
| stage6 merged vLLM context1280 batch16 text prompt | `20260626T084500Z-stage6-vllm-context1280-batch16-textprompt-256-256gen` | 256 | 256 | 97.66% | n/a | 0.1712s amortized | 108.34 | 632.74 |
| stage6 merged SGLang 0.5.8 HTTP conc16 default sampling | `20260626T090500Z-stage6-sglang058-http-conc16-prompt1000-256-128gen` | 256 | 128 | 98.44% | n/a | 0.1260s amortized | 109.87 | 872.10 |
| stage6 merged SGLang 0.5.8 HTTP conc16 greedy sampling | `20260626T092000Z-stage6-sglang058-http-conc16-greedy-prompt1024-224-128gen` | 224 | 128 | 96.09% | n/a | 0.1280s amortized | 106.72 | 833.54 |

Stage4 is the first checkpoint that consistently produces valid planner-shape JSON under a 256-token budget. The 64-example check is lower than the 16-example run, but still confirms a material jump from the 0-31% schema-valid range seen before the action-level rewrite.

Stage5 is the current best checkpoint. Filtering out commands longer than 160 characters directly addressed the main stage4 failure mode: truncated JSON after the model began writing long heredoc/script commands. On the 64-example check, stage5 improved schema validity from 76.56% to 96.88% and cut mean generation time from 7.2388s to 5.7663s.

The 192-token stage5 check is usable but not recommended as the default: it saves only about 0.11s versus the 256-token run while dropping schema validity from 96.88% to 87.50%.

Stage6 is the new best checkpoint. Reducing the target to at most two short commands, with 120-character command keystroke filtering and 160-character analysis/plan fields, preserved 96.88% schema validity at a 192-token budget and reduced mean generation time to 4.6234s. The 160-token budget is usable but not the default because it saves only about 0.11s while dropping schema validity to 93.75%.

Merging the stage6 LoRA into a full model created the stable base for serving optimization. The merged Transformers run cut mean generation time from 4.6234s to 2.1153s on the same GPU1, same 64 examples, same 192-token budget, while improving schema validity from 96.88% to 100.00%. Token throughput rose from 27.82 tok/s to 60.30 tok/s, and TTFT dropped from 0.0708s to 0.0483s.

Batched Transformers generation is the current best high-accuracy serving path. Batch8 preserves 100% schema validity and cuts amortized request latency to 0.7403s. Batch16 is better: it preserves 100% schema validity, cuts amortized request latency to 0.4462s, and reaches 277.85 tok/s on GPU1. The early unsorted batch32 check was not recommended because it dropped schema validity to 98.44%, but the later sorted-prompt batch32 check fixes that failure mode.

The Transformers path was improved again by prompt-length batching. Sorting prompts by token length before batching reduces left-padding work while keeping the same model and decoding stack. On a wider 256-example check, the original-order batch16 baseline with `max_new_tokens=192` kept 100% schema validity at 0.3621s amortized per request. Batch16 sorted with `max_new_tokens=256` kept 100% schema validity, kept command overlap essentially unchanged (`0.1399` vs `0.1393`), and cut amortized request latency to 0.2638s. Batch32 sorted with `max_new_tokens=256` kept 100% schema validity, improved command overlap to `0.1445`, and cut amortized request latency to 0.2173s. Batch48 and batch64 were both slower than batch32, and `max_seq_length=960` kept schema but lowered command overlap to `0.1298`, so neither should replace batch32.

A wider 512-example check exposed a residual long-command truncation failure mode. Batch32 sorted with explicit `attn_implementation=sdpa` and direct CUDA placement remained fast at `0.2187s` amortized, but schema validity dropped to 99.61% because two examples started writing long validation scripts and hit the 256-token cap. Batch16 on the same 512 examples reached 99.80% schema validity but was slower at `0.2541s`. Adding a compact output policy that discourages validation scripts/multiline commands, plus raising `max_new_tokens` to 320, restored 100.00% schema validity on the 512-example check, improved command overlap to `0.1520`, and kept latency at `0.2298s`.

Rejected serving shortcuts: `max_new_tokens=152/160` looked fine on 64 examples but dropped schema validity on 128 examples; `fp16` dropped schema validity to 92.19%; `max_seq_length=512` and `704` were faster in some checks but lost schema validity or command overlap.

Merged checkpoint:

```text
models/20260625T002525Z-qwen25-3b-stage6-merged
```

Merge metadata:

```text
models/20260625T002525Z-qwen25-3b-stage6-merged/merge_config.json
```

vLLM is intentionally installed in a separate serving environment, not in `AgentOpti`, so the merged Transformers run above remains a clean full-model benchmark:

```text
AgentOptiVLLM: vllm 0.18.1, torch 2.10.0+cu128
AgentOpti: unchanged, torch 2.11.0+cu128
```

The vLLM serving experiment improved after fixing the context budget. The first vLLM runs used `max_model_len=1024` with a `max_new_tokens=192` budget, which left only 832 prompt tokens and cut off useful task context. Raising vLLM to `max_model_len=1280` and `prompt_token_budget=1024`, plus using a tokenizer compatibility copy for the merged checkpoint, restored schema validity from about 60% to 97.66% on the 256-example check. It is also faster than the current Transformers default: `0.1712s` amortized versus `0.2638s`.

The remaining vLLM issue is quality, not just schema. On the same 256-example heldout slice, command overlap is `0.0993` for the best vLLM context1280 run versus `0.1445` for the Transformers batch32 sorted default. Strict structured JSON increased schema only to 98.44% on the 128-example check and lowered command overlap to `0.0926`, so constrained decoding alone is not enough.

SGLang 0.5.8 is now a confirmed CUDA-compatible serving route on this host when installed in `AgentOptiSGLang058` with `torch 2.9.1+cu128`. The latest SGLang 0.5.14 route is not usable on this driver because it installs `torch 2.11.0+cu130`, while the host driver is CUDA 12.8. SGLang 0.5.8 served the merged planner through `/generate` on GPU1 and reached `0.1260s` amortized with `872.10 tok/s` on a 128-example check, but command overlap was only `0.0856`. Forcing greedy sampling improved 32-example overlap but did not hold at 128 examples, where schema dropped to 96.09% and overlap was still only `0.1013`.

Serving route decision table:

| Route | Examples | Schema Valid | Command Overlap | Amortized Request | Tok/s | Decision |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Transformers batch32 compact policy 320 | 512 | 100.00% | 0.1520 | 0.2298s | 588.63 | current high-reliability default |
| Transformers batch32 SDPA/CUDA fast | 512 | 99.61% | 0.1434 | 0.2187s | 577.34 | speed profile |
| Transformers batch16 SDPA/CUDA fallback | 512 | 99.80% | 0.1414 | 0.2541s | 499.25 | lower-memory fallback |
| Transformers batch32 sorted | 256 | 100.00% | 0.1445 | 0.2173s | 577.51 | older 256-example fast check |
| Transformers batch64 sorted | 256 | 100.00% | 0.1427 | 0.2244s | 566.87 | slower than batch32 |
| Transformers batch16 seq768 sorted | 256 | 100.00% | 0.1333 | 0.2420s | 519.25 | speed candidate, needs task eval |
| vLLM context1280 batch16 text prompt | 256 | 97.66% | 0.0993 | 0.1712s | 632.74 | speed candidate only |
| SGLang 0.5.8 default sampling | 128 | 98.44% | 0.0856 | 0.1260s | 872.10 | fastest, quality gap too large |
| SGLang 0.5.8 greedy prompt1024/max224 | 128 | 96.09% | 0.1013 | 0.1280s | 833.54 | not better than default |

Current recommendation: keep the merged Transformers model with `batch_size=32`, prompt-length sorting, `max_seq_length=1024`, `max_new_tokens=320`, `bf16`, `attn_implementation=sdpa`, direct CUDA placement, and the compact output policy as the active high-reliability route. Use batch32 without the compact policy as the speed profile when 99.61% schema validity on the 512-example slice is acceptable, and use batch16 sorted as the lower-memory fallback. Treat vLLM context1280 and SGLang 0.5.8 as speed-priority serving candidates only after task-level validation or service-stack-specific fine-tuning. They are promising for throughput, but neither preserves the current command-overlap quality.

### What Changed

The useful optimization was not more generic SFT. It was changing the target surface:

```text
old target: verbose <think> text followed by JSON
stage2: JSON-only assistant target
stage3: strict JSON output instruction
stage4: action-level JSON with max 3 commands and shorter analysis/plan fields
stage5: short-command JSON, dropping command keystrokes longer than 160 chars
stage6: compact action2 JSON, dropping command keystrokes longer than 120 chars
```

This made the model stop spending most of the token budget on hidden reasoning and move toward a planner action object earlier.

### Next Direction

Do not replace the current OpenClaw planner with this checkpoint yet. Stage6 is now a stronger policy candidate for compact next-actions, and the merged batch32 compact-policy path brings amortized request latency down to 0.2298s on GPU1 while preserving 100% schema validity on the 512-example check, but it still needs runtime integration and task-level evaluation before replacing the deterministic planner.

The next optimization should be one of:

```text
1. continue stage6 with more compact short-command rows and evaluate at 64+ generation examples each time
2. train or distill against the target serving stack, especially vLLM/SGLang, because decoding-stack differences change command quality even when schema is mostly valid
3. wire the merged Transformers batch32 compact-policy path into a planner-serving wrapper with schema validation and batch16 fallback
4. distill the stage6 policy into Qwen2.5-1.5B-Instruct or a smaller planner if response speed is the main constraint
5. revisit speculative decoding or SGLang RadixAttention only after the serving-stack quality gap is closed
```

## OpenClaw Planner Benchmarks

Main deterministic benchmark:

```text
run: openclaw_benchmark_runs/20260623T143948Z-main-deterministic
tasks: 88 x 3 repeats
stop_criteria_met: true
```

| Strategy | Success | Mean Score | Mean Latency | Invalid Tools | Hallucinations | Loops | Unsafe Auto-Allow |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| greedy_topk | 5.68% | 0.7528 | 0.2884s | 0 | 0 | 0 | 0 |
| audit_astar | 100.00% | 1.0000 | 0.2829s | 0 | 0 | 0 | 0 |
| audit_reflexion | 100.00% | 1.0000 | 0.2948s | 0 | 0 | 0 | 0 |

No-hint control:

```text
tasks: 34 stripped multi-source planner tasks
enabled: openclaw_benchmark_runs/20260623T143906Z-nohint-model-enabled
disabled: openclaw_benchmark_runs/20260623T143906Z-nohint-model-disabled
```

| Condition | Success | Holdout Success | Mean Score |
| --- | ---: | ---: | ---: |
| learned profile model enabled | 97.06% | 100.00% | 0.9902 |
| learned profile model disabled | 5.88% | 0.00% | 0.7917 |

The existing OpenClaw planner path remains healthy. The new LoRA planner checkpoint is separate from that runtime and should not replace it until the strict JSON/action evaluation is materially better.
