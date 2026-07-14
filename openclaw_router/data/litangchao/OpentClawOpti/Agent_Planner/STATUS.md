# Agent Planner Status

Updated: 2026-06-27

## Route Decision

Use a new independent `Agent_Planner` training track:

```text
ToolBench SFT warm start
-> AgentScope 2.0 rollout runtime
-> automatic verifier/reward filtering
-> Agent Lightning RL or preference optimization
```

This route is mature enough to start because:

- ToolBench provides public tool-use training data and ToolLLaMA training/evaluation references.
- AgentScope 2.0 provides runtime abstractions for event logging, permission control, sandboxing, middleware, and task planning.
- Agent Lightning provides a framework direction for turning agent execution trajectories into training transitions/rewards.

## Downloaded Locally

Target root:

```text
/home/litangchao/OpenClawPOpti/data/litangchao/OpentClawOpti/Agent_Planner
```

Downloaded and generated:

```text
raw/qwen_terminal_toolbench_2b_full   7.9G
raw/toolbench_v1                      516M
raw/tau_bench_trajectories             15M
rewards/tau_bench_rewards.jsonl       6.6M
processed/qwen_terminal_toolbench_sft.jsonl                         8.4G
processed/toolbench_sft.jsonl                                        3.8G
processed/qwen_terminal_toolbench_sft_jsononly_200k.jsonl            879M
processed/qwen_terminal_toolbench_sft_jsononly_strict_100k.jsonl     441M
processed/qwen_terminal_toolbench_sft_jsononly_strict_action3_100k.jsonl 393M
processed/qwen_terminal_toolbench_sft_jsononly_strict_shortcmd160_100k.jsonl 359M
processed/qwen_terminal_toolbench_sft_jsononly_strict_shortcmd120_action2_100k.jsonl 338M
```

The current `Agent_Planner` directory is about `38G`, including the merged stage6 model below.

ToolBench v1 files:

```text
raw/toolbench_v1/data/train-00000-of-00004.parquet
raw/toolbench_v1/data/train-00001-of-00004.parquet
raw/toolbench_v1/data/train-00002-of-00004.parquet
raw/toolbench_v1/data/train-00003-of-00004.parquet
raw/toolbench_v1/data/validation-00000-of-00001.parquet
raw/toolbench_v1/benchmark/*.parquet
```

tau-bench trajectory sample files:

```text
raw/tau_bench_trajectories/Qwen3-235B-A22B-FP8.jsonl
raw/tau_bench_trajectories/gpt-4.1-mini.jsonl
raw/tau_bench_trajectories/gpt-4o-mini.jsonl
raw/tau_bench_trajectories/gpt-oss-20b.jsonl
```

## Primary Large Dataset Candidate

Selected and downloaded:

```text
LLM-OS-Models/Qwen-Terminal-ToolBench-Processed-Tokenized
subset: qwen35_2b_full_terminal_toolcall_processed_v1
reported size: 36.26 GiB
actual local size: 7.9G
reported rows: 1,011,776
file count selected by downloader: 20
```

The full repository reports about 77GB, so the downloader only selects the one subfolder and skips `cache-*.arrow` files by default. The Hugging Face card reports the selected subset as 36.26 GiB, while the final downloaded Arrow files occupy 7.9G locally. Use the local files as the operational source of truth.

Verified dry-run command:

```bash
python data/litangchao/OpentClawOpti/Agent_Planner/scripts/download_hf_subset.py \
  --source qwen_terminal_toolbench_2b_full \
  --target-root data/litangchao/OpentClawOpti/Agent_Planner/raw \
  --dry-run
```

Full download command:

```bash
python data/litangchao/OpentClawOpti/Agent_Planner/scripts/download_hf_subset.py \
  --source qwen_terminal_toolbench_2b_full \
  --target-root data/litangchao/OpentClawOpti/Agent_Planner/raw
```

Downloaded file check:

```text
20 files
17 Arrow shards
dataset_info.json
prepare_meta.json
state.json
no .part files remaining
```

Qwen metadata check:

```text
features: text:string
processed_rows: 1,011,776
template_model_id: Qwen/Qwen3.5-2B
chat_template_hash: 273d8e0e683b8850
```

## Reward Data Generated

Generated with:

```bash
python data/litangchao/OpentClawOpti/Agent_Planner/scripts/normalize_tau_trajectories.py \
  --input-dir data/litangchao/OpentClawOpti/Agent_Planner/raw/tau_bench_trajectories \
  --output data/litangchao/OpentClawOpti/Agent_Planner/rewards/tau_bench_rewards.jsonl
```

Result:

```text
examples: 660
successes: 248
success_rate: 0.3758
output_size: 6.6M
```

Agent-Lightning-style transition bridge generated with:

```bash
/home/litangchao/miniconda3/bin/conda run -n AgentOpti python \
  data/litangchao/OpentClawOpti/Agent_Planner/scripts/build_agent_lightning_transitions.py \
  --input data/litangchao/OpentClawOpti/Agent_Planner/rewards/tau_bench_rewards.jsonl \
  --output data/litangchao/OpentClawOpti/Agent_Planner/rewards/tau_bench_agent_lightning_transitions.jsonl \
  --credit final
```

Result:

```text
schema: agent_lightning_transition_v0
episodes: 660
transitions: 5,612
successful_episodes: 248
loop_episodes: 31
reward_sum: 239.5
output_size: 25M
```

## OpenClaw Architecture Trajectory Export

Planner runtime has been extended with explicit architecture events:

```text
task_queue_created
strategist_model_selection
architect_context
executor_started
verifier_result
planner_queue_closed
```

These events map the current architecture into trainable signals:

```text
Planner -> Task Queue -> Strategist -> Architect -> Executor -> Verifier
```

Exporter script:

```text
data/litangchao/OpentClawOpti/Agent_Planner/scripts/build_openclaw_architecture_trajectories.py
```

Smoke benchmark generated with:

```bash
/home/litangchao/miniconda3/envs/AgentOpti/bin/python backend/openclaw/benchmark.py \
  --strategies audit_reflexion \
  --repeats 1 \
  --split holdout \
  --output-dir data/litangchao/OpentClawOpti/Agent_Planner/eval_runs/20260630T_architecture_smoke
```

Smoke result:

```text
tasks: 27 holdout
success_rate: 100.00%
mean_score: 1.0000
mean_latency_seconds: 0.3779
mean_architecture_event_count: 32.7037
mean_subtask_count: 5.0000
mean_verifier_result_count: 5.0000
invalid_tool_call_count: 0
hallucinated_action_count: 0
unsafe_auto_allow_count: 0
```

Architecture-only export generated with:

```bash
/home/litangchao/miniconda3/envs/AgentOpti/bin/python \
  data/litangchao/OpentClawOpti/Agent_Planner/scripts/build_openclaw_architecture_trajectories.py \
  --input-root data/litangchao/OpentClawOpti/Agent_Planner/eval_runs/20260630T_architecture_smoke \
  --no-legacy \
  --output-transitions data/litangchao/OpentClawOpti/Agent_Planner/rewards/openclaw_architecture_smoke_transitions.jsonl \
  --output-sft data/litangchao/OpentClawOpti/Agent_Planner/processed/openclaw_architecture_smoke_sft.jsonl
```

Result:

```text
runs_scanned: 27
runs_exported: 27
transitions: 135
sft_rows: 135
mean_reward: 0.946519
model_tiers: large=3, medium=69, small=63
next_actions: await_human=7, next_subtask=127, replan=1
```

Full OpenClaw audit export generated with:

```bash
/home/litangchao/miniconda3/envs/AgentOpti/bin/python \
  data/litangchao/OpentClawOpti/Agent_Planner/scripts/build_openclaw_architecture_trajectories.py \
  --input-root data/benchmarks \
  --input-root data/litangchao/OpentClawOpti/Agent_Planner/eval_runs/20260630T_architecture_smoke \
  --input-root data/litangchao/OpentClawOpti/Agent_Planner/eval_runs/20260630T_architecture_full_r1 \
  --output-transitions data/litangchao/OpentClawOpti/Agent_Planner/rewards/openclaw_architecture_transitions.jsonl \
  --output-sft data/litangchao/OpentClawOpti/Agent_Planner/processed/openclaw_architecture_sft.jsonl
```

Result:

```text
runs_scanned: 4337
runs_exported: 4337
transitions: 21470
sft_rows: 21470
mean_reward: 0.947366
model_tiers: large=212, medium=4293, small=16965
next_actions: await_human=936, next_subtask=19953, replan=581
planner_strategies: audit_astar=7365, audit_reflexion=6965, greedy_topk=7140
source_modes: architecture=995, legacy=20475
```

Additional native architecture benchmark generated with:

```bash
/home/litangchao/miniconda3/envs/AgentOpti/bin/python backend/openclaw/benchmark.py \
  --strategies audit_astar,audit_reflexion \
  --repeats 1 \
  --split all \
  --output-dir data/litangchao/OpentClawOpti/Agent_Planner/eval_runs/20260630T_architecture_full_r1
```

Result:

```text
tasks: 88
audit_astar success_rate: 100.00%
audit_astar mean_architecture_event_count: 31.1818
audit_reflexion success_rate: 100.00%
audit_reflexion mean_architecture_event_count: 32.5455
invalid_tool_call_count: 0
hallucinated_action_count: 0
unsafe_auto_allow_count: 0
```

Balanced architecture data generated with:

```bash
/home/litangchao/miniconda3/envs/AgentOpti/bin/python \
  data/litangchao/OpentClawOpti/Agent_Planner/scripts/balance_openclaw_architecture_data.py \
  --transitions data/litangchao/OpentClawOpti/Agent_Planner/rewards/openclaw_architecture_transitions.jsonl \
  --sft data/litangchao/OpentClawOpti/Agent_Planner/processed/openclaw_architecture_sft.jsonl \
  --train-output data/litangchao/OpentClawOpti/Agent_Planner/processed/openclaw_architecture_balanced_train.jsonl \
  --heldout-output data/litangchao/OpentClawOpti/Agent_Planner/processed/openclaw_architecture_balanced_holdout.jsonl \
  --pair-output data/litangchao/OpentClawOpti/Agent_Planner/rewards/openclaw_architecture_counterfactual_pairs.jsonl \
  --target-per-stratum 800 \
  --max-per-stratum 1200 \
  --max-duplicates-per-row 5 \
  --heldout-ratio 0.1 \
  --pair-limit 12000 \
  --seed 17
```

Result:

```text
joined_rows: 21470
train_source_rows: 19318
heldout_rows: 2152
balanced_train_rows: 7102
preference_pairs: 12000
architecture native source rows before balance:
  large/await_human=10, large/replan=3, medium/await_human=41,
  medium/next_subtask=414, medium/replan=26, small/next_subtask=406
architecture native rows after balance:
  large/await_human=60, large/replan=18, medium/await_human=246,
  medium/next_subtask=800, medium/replan=156, small/next_subtask=800
pair_reasons:
  context_missing=5261
  medium_to_small=2469
  small_to_large=2630
  await_human_to_next=853
  next_to_replan=262
  replan_to_next=525
```

The SFT export is intentionally separate from the Stage7 command/action JSON training set. Use it for a dedicated architecture-policy adapter or reward/preference filtering first; do not mix it into the high-accuracy command planner without an ablation.

## Environment Notes

Created conda environment:

```text
name: AgentOpti
path: /home/litangchao/miniconda3/envs/AgentOpti
python: 3.11.15
```

Installed and verified in `AgentOpti`:

```text
pyarrow 24.0.0
pandas 3.0.3
datasets 5.0.0
transformers 5.12.1
torch 2.11.0+cu128
accelerate 1.14.0
peft 0.19.1
trl 1.6.0
agentscope 2.0.2
fsspec 2026.4.0
agentlightning 0.3.1
```

Agent Lightning source and install status:

```text
source: external/agent-lightning
git_head: 0b40cb7
project_name: agentlightning
version: 0.3.1
install: editable in AgentOpti
cli: agl
```

The earlier failed package name was `agent-lightning`; the correct PyPI/project name is `agentlightning`.

CUDA note:

```text
torch.cuda.is_available(): False
torch.version.cuda: 12.8
NVIDIA driver: 570.124.06
NVIDIA GPUs visible in /proc/driver/nvidia/gpus: 3 x NVIDIA L20
nvidia-smi works on the host when commands are run outside the Codex sandbox
/dev/nvidia* nodes exist on the host but are not visible in the default Codex sandbox
```

The PyTorch runtime mismatch is fixed by using cu128. GPU training commands must be run outside the default Codex sandbox so the process can see `/dev/nvidia*`.

Additional serving environments tested:

```text
AgentOptiVLLM:
  path: /home/litangchao/miniconda3/envs/AgentOptiVLLM
  vllm: 0.18.1
  torch: 2.10.0+cu128
  status: usable on GPU1 outside the Codex sandbox

AgentOptiSGLang:
  path: /home/litangchao/miniconda3/envs/AgentOptiSGLang
  sglang: 0.5.14
  torch: 2.11.0+cu130
  status: rejected on this host because driver 570.124.06 exposes CUDA 12.8, not CUDA 13

AgentOptiSGLang058:
  path: /home/litangchao/miniconda3/envs/AgentOptiSGLang058
  sglang: 0.5.8
  torch: 2.9.1+cu128
  status: CUDA smoke test passed on NVIDIA L20; SGLang /generate serving tested on GPU1
```

SGLang serving notes:

```text
launch fix: prepend /home/litangchao/miniconda3/envs/AgentOptiSGLang058/bin to PATH
reason: flashinfer JIT needs the conda env's ninja executable
tokenizer fix: use tokenizer_compat because newer tokenizer_config extra_special_tokens is a list
context note: SGLang rejects prompt_token_budget=1024 with max_new_tokens=256 at context_length=1280, so use prompt1000/256 or prompt1024/224
```

Host GPU remediation notes:

```text
/proc/driver/nvidia/version: 570.124.06
/proc/driver/nvidia/gpus: 3 x NVIDIA L20
/proc/devices: nvidia major 195, nvidia-uvm major 504
/usr/bin/nvidia-modprobe: setuid but owned by nobody:nogroup
```

No host GPU repair was needed. The failing checks came from the default sandbox view. Host-side read-only checks confirmed:

```text
GPU0: NVIDIA L20, 1 MiB used
GPU1: NVIDIA L20, about 15 GiB used by text-embeddings-router-80 before training
GPU2: NVIDIA L20, 1 MiB used
/dev/nvidia0, /dev/nvidia1, /dev/nvidia2, /dev/nvidiactl, /dev/nvidia-uvm exist on host
```

After `/dev/nvidia*` appears, verify the planner environment:

```bash
/home/litangchao/miniconda3/bin/conda run -n AgentOpti python -c "import torch; print(torch.__version__, torch.version.cuda, torch.cuda.is_available(), torch.cuda.device_count())"
```

Environment records:

```text
configs/AgentOpti.minimal-environment.yml
configs/agentopti_pip_freeze.txt
```

Prepared scripts:

```text
scripts/inspect_tabular_data.py
scripts/normalize_sft_data.py
scripts/normalize_tau_trajectories.py
scripts/build_agent_lightning_transitions.py
scripts/train_planner_sft.py
scripts/merge_lora_adapter.py
scripts/benchmark_vllm_planner.py
scripts/benchmark_http_planner.py
scripts/benchmark_transformers_batch_planner.py
scripts/launch_gpu1_sft.sh
scripts/launch_gpu1_sft_full.sh
scripts/evaluate_planner_sft.py
scripts/launch_gpu1_eval.sh
scripts/build_openclaw_no_hint_suite.py
scripts/build_jsononly_sft_data.py
scripts/launch_gpu1_sft_jsononly.sh
```

## Current Fast Planner Candidate

The current fast-response candidate is the merged stage6 checkpoint:

```text
adapter source: models/20260624T130000Z-qwen25-3b-gpu1-shortcmd120-action2-stage6-500/final_adapter
merged model: models/20260625T002525Z-qwen25-3b-stage6-merged
merge metadata: models/20260625T002525Z-qwen25-3b-stage6-merged/merge_config.json
eval run: eval_runs/20260625T002600Z-stage6-merged-transformers-192-64gen
```

The merged model was evaluated on GPU1 with the same 64-example heldout slice and 192-token budget used for the previous stage6 adapter check:

```text
schema_valid_rate: 100.00%
mean_ttft_seconds: 0.048273
mean_generation_seconds: 2.115309
mean_new_tokens: 127.5781
mean_tokens_per_second: 60.3011
gpu_peak_memory_mb: 6012.04
```

Compared with the stage6 LoRA adapter run (`20260624T133000Z-shortcmd120-action2-stage6-heldout-192-64gen`), the merged model keeps the same compact action2 target surface while cutting mean generation time from `4.623401s` to `2.115309s` on Transformers generation.

The best current serving/evaluation configuration is the merged model with batched Transformers generation, not vLLM. On the same GPU1, same 64-example heldout slice, same 192-token budget:

| Runtime | Eval Run | Batch | Schema Valid | Amortized Request | Tok/s | Peak GPU MB |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Transformers merged | `20260625T002600Z-stage6-merged-transformers-192-64gen` | 1 | 100.00% | 2.1153s | 60.30 | 6012.04 |
| Transformers merged | `20260625T034500Z-stage6-transformers-batch8-192-64gen` | 8 | 100.00% | 0.7403s | 172.35 | 6834.32 |
| Transformers merged | `20260625T035000Z-stage6-transformers-batch16-192-64gen` | 16 | 100.00% | 0.4462s | 277.85 | 7775.01 |
| Transformers merged | `20260625T035500Z-stage6-transformers-batch32-192-64gen` | 32 | 98.44% | 0.6790s | 182.94 | 9645.99 |
| vLLM | `20260625T010800Z-stage6-vllm-batch8-192-64gen` | 8 | 60.94% | 0.2157s | 302.50 | n/a |

Conclusion from the initial 64-example batch check: use `batch_size=16` before prompt sorting. It preserves the 100% schema-valid rate of the single-request Transformers baseline while improving amortized request latency by about `4.74x` and token throughput by about `4.61x`. The early unsorted batch32 run was not recommended because it was slower than batch16 and dropped schema validity to 98.44%.

The next Transformers optimization is prompt-length batching. It keeps the model/runtime on Transformers but groups similarly sized prompts before generation, which reduces left-padding work inside each batch. The high-accuracy default now uses:

```text
batch_size: 32
max_seq_length: 1024
max_new_tokens: 256
dtype: bf16
attn_implementation: sdpa
device_placement: cuda
sort_by_prompt_length: true
retry_invalid_extra_output_policy: hard short-command repair clamp
retry_invalid_max_new_tokens: 272
```

256-example GPU1 comparison:

| Config | Eval Run | Schema Valid | Command Overlap | Amortized Request | Tok/s | Prompt Padding |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| batch16, original order, 192 tokens | `20260625T054500Z-stage6-transformers-batch16-192-256gen` | 100.00% | 0.1393 | 0.3621s | 347.79 | 21.54% |
| batch16, sorted prompts, 192 tokens | `20260625T054000Z-stage6-transformers-batch16-192-sort-256gen` | 99.61% | 0.1398 | 0.2598s | 487.94 | 3.41% |
| batch16, sorted prompts, 256 tokens | `20260625T055000Z-stage6-transformers-batch16-256-sort-256gen` | 100.00% | 0.1399 | 0.2638s | 481.10 | 3.41% |
| batch16, sorted prompts, 224 tokens | `20260626T093000Z-stage6-transformers-batch16-224-sort-256gen` | 99.61% | 0.1398 | 0.2634s | 481.76 | 3.41% |
| batch32, sorted prompts, 256 tokens | `20260626T093500Z-stage6-transformers-batch32-256-sort-256gen` | 100.00% | 0.1445 | 0.2173s | 577.51 | 6.71% |
| batch48, sorted prompts, 256 tokens | `20260626T100000Z-stage6-transformers-batch48-256-sort-256gen` | 100.00% | 0.1350 | 0.2324s | 543.62 | 9.01% |
| batch64, sorted prompts, 256 tokens | `20260626T094000Z-stage6-transformers-batch64-256-sort-256gen` | 100.00% | 0.1427 | 0.2244s | 566.87 | 12.83% |
| batch32, seq960, sorted prompts, 256 tokens | `20260626T100500Z-stage6-transformers-batch32-256-seq960-sort-256gen` | 100.00% | 0.1298 | 0.2176s | 578.28 | 6.75% |
| speed candidate: seq768, sorted prompts, 256 tokens | `20260625T055500Z-stage6-transformers-batch16-256-seq768-sort-256gen` | 100.00% | 0.1333 | 0.2420s | 519.25 | 3.00% |

The sorted batch32 256-token configuration remains the best pure speed profile on the 256-example check. It preserves 100% schema validity, improves command overlap from `0.1399` to `0.1445` versus the sorted batch16 path, and improves amortized request latency from `0.2638s` to `0.2173s` on GPU1. Batch48 and batch64 are not better because padding and decode work rise. The seq960/seq768 variants are not better because they trim context and lower command overlap.

512-example GPU1 validation:

| Config | Eval Run | Schema Valid | Command Overlap | Amortized Request | Tok/s | Decision |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| batch32, SDPA/CUDA, 256 tokens | `20260626T102500Z-stage6-transformers-batch32-256-sort-sdpa-cuda-512gen` | 99.61% | 0.1434 | 0.2187s | 577.34 | fastest 512-example profile |
| batch16, SDPA/CUDA, 256 tokens | `20260626T103000Z-stage6-transformers-batch16-256-sort-sdpa-cuda-512gen` | 99.80% | 0.1414 | 0.2541s | 499.25 | lower-memory fallback |
| batch32, compact policy, 256 tokens | `20260626T103500Z-stage6-transformers-batch32-256-sort-sdpa-cuda-clamp-512gen` | 99.80% | 0.1520 | 0.2284s | 591.82 | quality-positive but one truncation remains |
| batch32, compact policy, 320 tokens | `20260626T104000Z-stage6-transformers-batch32-320-sort-sdpa-cuda-clamp-512gen` | 100.00% | 0.1520 | 0.2298s | 588.63 | superseded by medium policy/retry profiles |

The compact policy fixes the residual long-command failure mode where the model starts writing validation scripts such as multiline `python3 -c` checks and hits the generation cap. Raising the cap from 256 to 320 adds only about `0.0013s` versus the compact-policy 256-token check because nearly all examples still stop early. It restores 100% schema validity on 512 examples and keeps latency below the batch16 fallback.

2026-06-27 1k GPU1 validation:

| Config | Eval Run | Schema Valid | Command Overlap | Amortized Request | Tok/s | Retry Count | Decision |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| short compact policy, 288 tokens | `20260627T000500Z-stage6-transformers-batch32-288-sort-sdpa-cuda-shortclamp-512gen` | 99.61% | 0.1318 | 0.2584s | 510.99 | 0 | rejected: too terse, worse quality and speed |
| medium compact policy, 272 tokens | `20260627T002000Z-stage6-transformers-batch32-272-sort-sdpa-cuda-midclamp-512gen` | 100.00% | 0.1595 | 0.2266s | 595.19 | 0 | good no-retry compact profile |
| medium compact policy, seq1088 | `20260627T002500Z-stage6-transformers-batch32-272-seq1088-sort-sdpa-cuda-midclamp-512gen` | 100.00% | 0.1546 | 0.2167s | 623.24 | 0 | speed candidate, lower overlap |
| medium compact policy, seq1056 | `20260627T003000Z-stage6-transformers-batch32-272-seq1056-sort-sdpa-cuda-midclamp-512gen` | 99.41% | 0.1535 | 0.2383s | 571.56 | 0 | rejected |
| fast first pass + hard retry | `20260627T004500Z-stage6-transformers-batch32-256-fast-retry-hardclamp272-1kgen` | 100.00% | 0.1525 | 0.2120s | 594.42 | 3 | current default |
| medium compact + hard retry | `20260627T005500Z-stage6-transformers-batch32-272-midclamp-retry-hardclamp-1kgen` | 100.00% | 0.1598 | 0.2304s | 584.44 | 2 | quality-priority profile |

The new default is selective repair: run the fast 256-token profile first and retry only schema-invalid generations with a stricter no-validation/no-script repair prompt. On the full 1k heldout file, the first pass reached 99.70% schema validity at `0.2093s` amortized; retrying the three invalid generations restored 100.00% schema validity at `0.2120s`. This is faster than applying the compact policy to every request. Use the global medium compact policy plus hard retry when command overlap is more important than latency.

Do not use these attempted shortcuts as defaults:

```text
max_new_tokens=152/160: passed 64 examples but dropped schema on 128 examples
max_new_tokens=224: saves almost nothing and drops schema to 99.61% on 256 examples
dtype=fp16: dropped schema to 92.19% on the 64-example check
max_seq_length=512: dropped schema to 97.66% and lowered command overlap on 128 examples
max_seq_length=704: dropped schema to 98.44% on 128 examples
max_seq_length=960: preserves schema on 256 examples but lowers command overlap to 0.1298
max_seq_length=1056: drops schema to 99.41% on 512 examples
dynamic max-batch-prompt-tokens=32768: preserves schema but slows to 0.2406s on 256 examples
short compact policy: drops schema to 99.61%, lowers overlap to 0.1318, and slows to 0.2584s
batch48 sorted: preserves schema but is slower and lowers command overlap
batch64 sorted: preserves schema but is slower than batch32 because prompt padding rises
```

vLLM is not installed in `AgentOpti` yet:

```text
importlib.util.find_spec("vllm"): False
pip show vllm: package not found
```

The serving benchmark uses a separate environment so the known-good training/evaluation environment remains unchanged:

```text
name: AgentOptiVLLM
path: /home/litangchao/miniconda3/envs/AgentOptiVLLM
python: 3.11.15
vllm: 0.18.1
torch: 2.10.0+cu128
torch_cuda: 12.8
size: 9.5G
```

`vllm==0.23.0` was not used because the default dependency path resolved to CUDA 13 packages, while the host driver is `570.124.06`. The installed `vllm==0.18.1` path resolves to `torch==2.10.0+cu128`, which is compatible with the current driver/GPU setup.

vLLM GPU smoke:

```text
CUDA_VISIBLE_DEVICES=1
torch.cuda.is_available(): True
device: NVIDIA L20
vllm_version: 0.18.1
```

vLLM benchmark results on the same 64-example heldout slice:

```text
eval_run: eval_runs/20260625T010100Z-stage6-vllm-batch1-192-64gen
batch_size: 1
schema_valid_rate: 59.38%
mean_amortized_request_seconds: 0.663544
mean_new_tokens: 63.4219
tokens_per_second: 95.5805
```

```text
eval_run: eval_runs/20260625T010800Z-stage6-vllm-batch8-192-64gen
batch_size: 8
schema_valid_rate: 60.94%
mean_amortized_request_seconds: 0.215650
mean_new_tokens: 65.2344
tokens_per_second: 302.5007
```

Conclusion: vLLM is connected to GPU1 and is much faster, but this stage6 checkpoint is not yet a direct vLLM replacement because vLLM decoding often terminates after about 8 tokens in the middle of the JSON object. Token-prompt input, `ignore_eos`, eos suppression, `min_tokens`, and vLLM structured JSON schema smoke tests did not recover the 100% schema-valid rate seen with Transformers merged generation. Keep the Transformers merged model as the current accuracy baseline; use vLLM only as a speed experiment or as the first pass in a future validate-and-fallback serving path.

## Training Launch Attempt

GPU1 smoke SFT launch command:

```bash
/home/litangchao/OpenClawPOpti/data/litangchao/OpentClawOpti/Agent_Planner/scripts/launch_gpu1_sft.sh
```

Result on 2026-06-23:

```text
status: blocked before training
reason: /dev/nvidia1 is missing in this session
log: logs/20260623T055846Z-qwen25-3b-gpu1-smoke.log
output_dir_precreated: models/20260623T055846Z-qwen25-3b-gpu1-smoke
checkpoint_written: no
```

The launch script intentionally fails fast when GPU1 is not exposed, so no CPU fallback training was started.

Host-side GPU1 smoke SFT completed on 2026-06-23:

```text
status: completed
gpu: GPU1 / NVIDIA L20
base_model: Qwen/Qwen2.5-3B-Instruct local cache
train_file: processed/qwen_terminal_toolbench_sft_sample.jsonl
max_steps: 50
max_seq_length: 1024
max_train_samples: 2000
lora_r: 16
lora_alpha: 32
bf16: true
train_runtime: 84.63s
train_loss: 0.3958
checkpoint: models/20260623T060347Z-qwen25-3b-gpu1-smoke/checkpoint-50
final_adapter: models/20260623T060347Z-qwen25-3b-gpu1-smoke/final_adapter
log: logs/20260623T060347Z-qwen25-3b-gpu1-smoke.log
```

Streaming large SFT completed on GPU1 on 2026-06-23:

```text
status: completed
pid: exited
gpu: GPU1 / NVIDIA L20
base_model: Qwen/Qwen2.5-3B-Instruct local cache
train_file: processed/qwen_terminal_toolbench_sft.jsonl
streaming: true
shuffle_buffer: 10000
max_train_samples: 200000
max_steps: 5000
max_seq_length: 1024
effective_batch: 8
lora_r: 16
lora_alpha: 32
bf16: true
save_steps: 500
output_dir: models/20260623T063028Z-qwen25-3b-gpu1-stream200k-5k
checkpoint: models/20260623T063028Z-qwen25-3b-gpu1-stream200k-5k/checkpoint-5000
final_adapter: models/20260623T063028Z-qwen25-3b-gpu1-stream200k-5k/final_adapter
log: logs/20260623T063028Z-qwen25-3b-gpu1-stream200k-5k.log
runtime: about 3:31:31
last_logged_loss_step_5000: 0.3573
observed_gpu_memory: about 9.2 GiB for training process, plus existing text-embeddings-router-80
gpu_after_completion: training process released; only text-embeddings-router-80 remained on GPU1
```

Earlier eager-load attempts were stopped before training because JSONL `load_dataset` spent several minutes CPU-parsing the full file before GPU use. The active run uses streaming JSONL and batch-time tokenization.

JSON-only/action-level optimization passes completed on GPU1 on 2026-06-24:

```text
stage2:
  run: models/20260624T070128Z-qwen25-3b-gpu1-jsononly-stage2-1k
  init_adapter: models/20260623T063028Z-qwen25-3b-gpu1-stream200k-5k/final_adapter
  train_file: processed/qwen_terminal_toolbench_sft_jsononly_200k.jsonl
  max_steps: 1000
  final_adapter: models/20260624T070128Z-qwen25-3b-gpu1-jsononly-stage2-1k/final_adapter
  last_logged_loss: 0.2910

stage3:
  run: models/20260624T081500Z-qwen25-3b-gpu1-strict-json-stage3-500
  init_adapter: models/20260624T070128Z-qwen25-3b-gpu1-jsononly-stage2-1k/final_adapter
  train_file: processed/qwen_terminal_toolbench_sft_jsononly_strict_100k.jsonl
  max_steps: 500
  final_adapter: models/20260624T081500Z-qwen25-3b-gpu1-strict-json-stage3-500/final_adapter
  last_logged_loss: 0.3022

stage4:
  run: models/20260624T091500Z-qwen25-3b-gpu1-action3-stage4-500
  init_adapter: models/20260624T081500Z-qwen25-3b-gpu1-strict-json-stage3-500/final_adapter
  train_file: processed/qwen_terminal_toolbench_sft_jsononly_strict_action3_100k.jsonl
  max_steps: 500
  final_adapter: models/20260624T091500Z-qwen25-3b-gpu1-action3-stage4-500/final_adapter
  last_logged_loss: 0.2521

stage5:
  run: models/20260624T111500Z-qwen25-3b-gpu1-shortcmd160-stage5-500
  init_adapter: models/20260624T091500Z-qwen25-3b-gpu1-action3-stage4-500/final_adapter
  train_file: processed/qwen_terminal_toolbench_sft_jsononly_strict_shortcmd160_100k.jsonl
  max_steps: 500
  final_adapter: models/20260624T111500Z-qwen25-3b-gpu1-shortcmd160-stage5-500/final_adapter
  train_runtime: 19:10
  train_loss: 0.2640

stage6:
  run: models/20260624T130000Z-qwen25-3b-gpu1-shortcmd120-action2-stage6-500
  init_adapter: models/20260624T111500Z-qwen25-3b-gpu1-shortcmd160-stage5-500/final_adapter
  train_file: processed/qwen_terminal_toolbench_sft_jsononly_strict_shortcmd120_action2_100k.jsonl
  max_steps: 500
  final_adapter: models/20260624T130000Z-qwen25-3b-gpu1-shortcmd120-action2-stage6-500/final_adapter
  train_runtime: 19:01
  train_loss: 0.2431
```

Current recommended checkpoint:

```text
models/20260624T130000Z-qwen25-3b-gpu1-shortcmd120-action2-stage6-500/final_adapter
```

## Evaluation Results

Evaluation summary:

```text
EVAL_SUMMARY.md
```

Base-vs-LoRA heldout evaluation:

```text
run: eval_runs/20260623T143655Z-base-vs-lora-heldout
heldout_start_line: 300001
loss_examples: 64
generation_examples: 16
max_new_tokens: 256
base_loss: 1.811775
adapter_loss: 1.056539
adapter_relative_loss_improvement: 41.68%
base_valid_json_rate: 12.50%
adapter_valid_json_rate: 0.00%
base_generation_speed: 60.63 tok/s
adapter_generation_speed: 27.88 tok/s
```

Adapter-only long generation check:

```text
run: eval_runs/20260623T144420Z-lora-heldout-gen768
generation_examples: 8
max_new_tokens: 768
adapter_valid_json_rate: 50.00%
adapter_schema_valid_rate: 50.00%
mean_ttft: 0.0966s
mean_generation_seconds: 21.6793s
mean_generation_speed: 28.28 tok/s
```

JSON-only/action-level optimization evaluation:

```text
stage2_eval: eval_runs/20260624T080900Z-jsononly-stage2-heldout
stage2_schema_valid_at_256: 31.25%

stage3_eval: eval_runs/20260624T084200Z-strict-json-stage3-heldout
stage3_schema_valid_at_256: 31.25%

stage4_eval: eval_runs/20260624T101000Z-action3-stage4-heldout
stage4_schema_valid_at_256_16gen: 87.50%
stage4_mean_generation_seconds_16gen: 7.1978s
stage4_mean_ttft_16gen: 0.0672s

stage4_64gen_eval: eval_runs/20260624T103100Z-action3-stage4-heldout-64gen
stage4_schema_valid_at_256_64gen: 76.56%
stage4_mean_generation_seconds_64gen: 7.2388s
stage4_mean_ttft_64gen: 0.0767s

stage4_192tok_eval: eval_runs/20260624T102000Z-action3-stage4-heldout-192
stage4_schema_valid_at_192_16gen: 43.75%

stage5_64gen_eval: eval_runs/20260624T114000Z-shortcmd160-stage5-heldout-64gen
stage5_schema_valid_at_256_64gen: 96.88%
stage5_mean_generation_seconds_256_64gen: 5.7663s
stage5_mean_new_tokens_256_64gen: 164.2812
stage5_mean_ttft_256_64gen: 0.0703s

stage5_192tok_eval: eval_runs/20260624T115000Z-shortcmd160-stage5-heldout-192-64gen
stage5_schema_valid_at_192_64gen: 87.50%
stage5_mean_generation_seconds_192_64gen: 5.6561s
stage5_mean_new_tokens_192_64gen: 159.6250

stage6_192tok_eval: eval_runs/20260624T133000Z-shortcmd120-action2-stage6-heldout-192-64gen
stage6_schema_valid_at_192_64gen: 96.88%
stage6_mean_generation_seconds_192_64gen: 4.6234s
stage6_mean_new_tokens_192_64gen: 128.6562
stage6_mean_ttft_192_64gen: 0.0708s

stage6_160tok_eval: eval_runs/20260624T134000Z-shortcmd120-action2-stage6-heldout-160-64gen
stage6_schema_valid_at_160_64gen: 93.75%
stage6_mean_generation_seconds_160_64gen: 4.5087s
stage6_mean_new_tokens_160_64gen: 127.1094
```

Interpretation:

```text
The adapter learned the heldout token distribution, but the current target format is too verbose for a fast planner.
It frequently starts with long <think> spans and needs a larger generation budget before a complete JSON action appears.
The short-command action2 stage6 adapter is the current best checkpoint.
Use max_new_tokens=192 for now: it preserves 96.88% schema validity on the 64-example check while cutting mean generation time to 4.6234s.
The 160-token budget is usable but not the default: it saves only about 0.11s and drops schema validity to 93.75%.
This is now a stronger fast-planner policy checkpoint for compact next-actions, but still needs runtime integration and task-level evaluation before replacing the existing OpenClaw planner.
```

OpenClaw benchmark refresh:

```text
main: openclaw_benchmark_runs/20260623T143948Z-main-deterministic
no_hint_model_enabled: openclaw_benchmark_runs/20260623T143906Z-nohint-model-enabled
no_hint_model_disabled: openclaw_benchmark_runs/20260623T143906Z-nohint-model-disabled

main audit_astar success: 100.00%
main audit_reflexion success: 100.00%
main greedy_topk success: 5.68%
main stop_criteria_met: true
no_hint enabled success: 97.06%
no_hint enabled holdout success: 100.00%
no_hint disabled success: 5.88%
no_hint disabled holdout success: 0.00%
```

## Next Implementation Steps

1. Convert ToolBench parquet rows into planner SFT JSONL. Done in `AgentOpti`:

```bash
/home/litangchao/miniconda3/bin/conda run -n AgentOpti python \
  data/litangchao/OpentClawOpti/Agent_Planner/scripts/normalize_sft_data.py \
  --kind toolbench \
  --input data/litangchao/OpentClawOpti/Agent_Planner/raw/toolbench_v1/data \
  --output data/litangchao/OpentClawOpti/Agent_Planner/processed/toolbench_sft.jsonl
```

   Result:

```text
processed/toolbench_sft.jsonl
examples: 188,304
size: 3.8G
```

   Qwen SFT text conversion done in `AgentOpti`:

```bash
/home/litangchao/miniconda3/bin/conda run -n AgentOpti python \
  data/litangchao/OpentClawOpti/Agent_Planner/scripts/normalize_sft_data.py \
  --kind qwen_text \
  --input data/litangchao/OpentClawOpti/Agent_Planner/raw/qwen_terminal_toolbench_2b_full/qwen35_2b_full_terminal_toolcall_processed_v1 \
  --output data/litangchao/OpentClawOpti/Agent_Planner/processed/qwen_terminal_toolbench_sft.jsonl
```

   Result:

```text
processed/qwen_terminal_toolbench_sft.jsonl
examples: 1,011,776
size: 8.4G
```

2. Convert tau-bench trajectories into automatic reward examples. Done for the initial 4-model sample:

```bash
python data/litangchao/OpentClawOpti/Agent_Planner/scripts/normalize_tau_trajectories.py \
  --input-dir data/litangchao/OpentClawOpti/Agent_Planner/raw/tau_bench_trajectories \
  --output data/litangchao/OpentClawOpti/Agent_Planner/rewards/tau_bench_rewards.jsonl
```

3. Define a common training schema:

```json
{
  "goal": "...",
  "tools": ["..."],
  "trajectory": ["..."],
  "target_next_action": "...",
  "reward": {
    "success": true,
    "invalid_tool": false,
    "policy_violation": false,
    "loop": false
  }
}
```

4. Build an AgentScope 2.0 rollout runner that emits planner transitions.
5. Attach automatic verifier rewards.
6. Continue from the stage6 adapter with more compact short-command data and schema-first validation.
7. For speed and reliability, keep the merged model on Transformers batch32 sorted prompts with SDPA, direct CUDA placement, a 256-token first pass, and selective hard retry for schema-invalid outputs. Use global medium compact policy plus hard retry as the quality-priority profile, and batch16 sorted as the lower-memory fallback. Treat vLLM/SGLang as separate validate-and-fallback or serving-stack fine-tuning projects before using either as a direct replacement.

## 2026-06-30 Stage12 Architecture-Policy Compact Planner

Goal: adapt the model planner to the current OpenClaw architecture diagram:
Strategist chooses model tier, Architect chooses context policy, executor kind
routes the subtask, and verifier decides the next action.

Key scripts/tests:

```text
scripts/build_compact_architecture_policy_sft.py
scripts/evaluate_architecture_policy.py
scripts/summarize_architecture_policy_runs.py
scripts/validate_openclaw_architecture_data.py
tests/test_openclaw_architecture_compact_sft.py
tests/test_openclaw_architecture_policy_eval.py
tests/test_openclaw_architecture_summary.py
tests/test_openclaw_architecture_validator.py
```

Data:

```text
processed/openclaw_architecture_native_balanced_train.jsonl      2320 rows
processed/openclaw_architecture_native_balanced_holdout.jsonl      95 rows
processed/openclaw_architecture_native_compact_train.jsonl       2320 rows
processed/openclaw_architecture_native_compact_holdout.jsonl       95 rows
rewards/openclaw_architecture_native_counterfactual_pairs.jsonl   900 rows
```

Native data validation:

```text
eval_runs/20260630T_architecture_native_data_validation/summary.json
ok=true
issue_count=0
balanced_train=2320
heldout=95
pairs=900
balanced_train_heldout_overlap=0
```

Negative/learning results:

```text
models/20260630T-architecture-policy-balanced-smoke-20
  all-data target lowered loss, but mixed legacy/native data and full command JSON target kept the model in command-planner mode.

models/20260630T-architecture-policy-native-smoke-40
  native-only full target did not fix the format problem.
  architecture eval: schema_valid=14.06%, model_tier=1.56%, next_action=7.81%, context_policy=1.56%, executor_kind=0.00%.
```

Promoted Stage12 candidate:

```text
models/20260630T-architecture-policy-compact-continue200/final_adapter
eval_runs/20260630T_architecture_policy_compact_continue200_eval95
eval_runs/20260630T_architecture_policy_compact_continue200_eval95/architecture_policy_eval_v4_alias
```

Metrics on 95-row native compact heldout:

```text
valid_json_rate=100.00%
architecture_schema_valid_rate=100.00%
model_tier_accuracy=97.89%
next_action_accuracy=94.74%
context_policy_accuracy=100.00%
executor_kind_accuracy=100.00%
loss=0.004614
perplexity=1.0046
mean_generation_seconds=2.468761
mean_new_tokens=62.4421
gpu_peak_memory_mb=7233.12
```

Iteration comparison:

```text
eval_runs/20260630T_architecture_policy_key_iterations_summary.md
```

Interpretation:

```text
Compact architecture targets are the first successful route for adapting the
model planner to the proposed Strategist/Architect/Executor/Verifier architecture.
The model now reliably emits compact policy JSON, and alias canonicalization maps
tool-shaped executor outputs back to the architecture enum.

This is still not a runtime replacement for backend/openclaw/planner.py:
the heldout is only 95 native architecture rows, not the 1k command-planner benchmark.
It should be treated as a candidate architecture-policy subplanner. Before runtime
integration, expand native architecture heldout to at least 1k rows, add a constrained
enum decoder or postprocessor for next_action, and run task-level benchmark against
the profile-aware LocalAuditPlanner.
```

Recommended next step:

```text
Build a lightweight serving wrapper around compact outputs:
1. parse compact JSON,
2. canonicalize model_tier/context_policy/executor_kind/next_action aliases,
3. apply deterministic tool priors for model_tier/executor_kind,
4. add a next_action guard for rare replan/await_human decisions,
5. evaluate on an expanded native architecture heldout and then task-level benchmark.
```

## 2026-06-30 Stage12 Serving Wrapper Follow-up

Implemented the lightweight wrapper recommended above:

```text
scripts/apply_architecture_policy_wrapper.py
tests/test_openclaw_architecture_policy_wrapper.py
```

Wrapper behavior:

```text
1. parse compact model JSON,
2. normalize field aliases through evaluate_architecture_policy.py,
3. apply tool priors for model_tier and executor_kind,
4. apply permission-mode next_action guards for variable execution tools,
5. optionally read eval_samples.jsonl so offline evaluation uses full prompts rather than truncated task_preview strings.
```

Best wrapper evaluation:

```text
input:
  eval_runs/20260630T_architecture_policy_compact_continue200_eval95/generations.jsonl
eval_samples:
  eval_runs/20260630T_architecture_policy_compact_continue200_eval95/eval_samples.jsonl
wrapped output:
  eval_runs/20260630T_architecture_policy_compact_continue200_eval95/wrapped_generations_v3_samples.jsonl
metrics:
  eval_runs/20260630T_architecture_policy_compact_continue200_eval95/architecture_policy_eval_v6_wrapped_samples/metrics.json
```

Wrapper rule counts:

```text
permission_guard:next_action:ACCEPT_EDITS = 3
permission_guard:next_action:DONT_ASK = 1
permission_guard:next_action:EXPLORE = 1
tool_prior:model_tier = 2
```

95-row native architecture heldout after wrapper:

```text
valid_json_rate=100.00%
architecture_schema_valid_rate=100.00%
model_tier_accuracy=100.00%
next_action_accuracy=100.00%
context_policy_accuracy=100.00%
executor_kind_accuracy=100.00%
```

Important caveat:

```text
This is still an architecture-policy offline heldout result. Do not wire it into
backend/openclaw/planner.py as a runtime replacement until it passes a larger
native architecture heldout, then the task-level OpenClaw benchmark. The next
useful implementation step is to package the wrapper as a small importable policy
module and run it inside a task-level benchmark adapter without replacing
LocalAuditPlanner.
```

## 2026-07-01 Stage13 Architecture-Policy Shadow Adapter

Implemented the next step as a non-runtime-replacing shadow adapter:

```text
scripts/architecture_policy.py
scripts/apply_architecture_policy_wrapper.py
scripts/benchmark_architecture_policy_shadow.py
tests/test_openclaw_architecture_policy_shadow.py
```

Serving wrapper improvements:

```text
1. moved wrapper logic into importable architecture_policy.py,
2. added deterministic context_policy priors per OpenClaw tool role,
3. added BYPASS handling for variable execution tools,
4. preserved await_human for dangerous mutating actions even under edit-friendly modes,
5. added a task-level shadow benchmark over LocalAuditPlanner architecture events.
```

Task-level shadow result:

```text
input: eval_runs/20260630T_architecture_full_r1
output: eval_runs/20260701T_architecture_policy_shadow_full_r1
event_files_seen: 176
rows: 860
exact_policy_match: 100.00%
model_tier_accuracy: 100.00%
verifier_next_action_accuracy: 100.00%
context_policy_accuracy: 100.00%
executor_kind_accuracy: 100.00%
```

Next-action ablation:

```text
output: eval_runs/20260701T_architecture_policy_shadow_full_r1_no_next_prior
exact_policy_match: 30.93%
verifier_next_action_accuracy: 30.93%
model_tier/context_policy/executor_kind: 100.00%
```

Stage12 regression check after module extraction:

```text
output: eval_runs/20260701T_architecture_policy_compact_continue200_eval95_module_wrapped
rows: 95
schema_valid_rate: 100.00%
model_tier_accuracy: 100.00%
next_action_accuracy: 100.00%
context_policy_accuracy: 100.00%
executor_kind_accuracy: 100.00%
```

Interpretation:

```text
The architecture-policy wrapper is now a stable normalization/safety layer for
compact model outputs and task-level event replay. This still does not prove the
learned architecture-policy model can replace LocalAuditPlanner, because the
860-row shadow result is rule/prior replay against current deterministic event
labels. The next useful optimization is to run the learned model on a larger
native architecture heldout and feed its outputs through the same shadow adapter.
```

## 2026-07-01 Stage14 Learned Architecture-Policy 1k Native Eval

Goal:

```text
Move the architecture-policy route from the earlier 95-row native heldout to a
larger runtime-shaped learned-model evaluation:
1. build at least 1k native architecture rows,
2. run the learned compact architecture-policy model,
3. score raw outputs and serving-wrapper outputs under the same reference,
4. keep the route separate from backend/openclaw/planner.py.
```

Native data:

```text
benchmark output: eval_runs/20260701T_architecture_full_r2
strategies: audit_astar,audit_reflexion
repeats: 2
runs_exported: 352
transition rows: 1720
sft rows: 1720
model_tiers: large=20, medium=944, small=756
next_actions: await_human=100, next_subtask=1560, replan=60
```

Shadow rule/prior replay on the full 1720-row native event set:

```text
output: eval_runs/20260701T_architecture_policy_shadow_full_r2
rows: 1720
exact_policy_match: 100.00%
model_tier_accuracy: 100.00%
verifier_next_action_accuracy: 100.00%
context_policy_accuracy: 100.00%
executor_kind_accuracy: 100.00%
```

Learned model generation:

```text
model: models/20260630T-architecture-policy-compact-continue200/final_adapter
base: models/20260627T-stage7-verifier-combined3k-500-merged
eval rows: 1000
output: eval_runs/20260701T_architecture_policy_model_stage14_r2_1k
batch_size: 32
max_new_tokens: 96
GPU: CUDA_VISIBLE_DEVICES=1
total_generation_seconds: 149.062657
mean_amortized_generation_seconds: 0.149063
tokens_per_second: 455.862
gpu_peak_memory_mb: 10351.96
```

Raw learned-model result:

```text
eval: eval_runs/20260701T_architecture_policy_model_stage14_r2_1k/raw_eval
schema_valid_rate: 99.90%
model_tier_accuracy: 97.60%
next_action_accuracy: 93.10%
context_policy_accuracy: 98.90%
executor_kind_accuracy: 98.00%
parse_failures: 1
```

Best serving-wrapper result:

```text
wrapped output: eval_runs/20260701T_architecture_policy_model_stage14_r2_1k/wrapped_generations_v4_promptctx_deployonly.jsonl
eval: eval_runs/20260701T_architecture_policy_model_stage14_r2_1k/wrapped_eval_v4_promptctx_deployonly
schema_valid_rate: 100.00%
model_tier_accuracy: 100.00%
next_action_accuracy: 100.00%
context_policy_accuracy: 100.00%
executor_kind_accuracy: 100.00%
```

Wrapper rule counts for the 1k best run:

```text
permission_guard:next_action:ACCEPT_EDITS = 49
permission_guard:next_action:BYPASS = 1
permission_guard:next_action:DEFAULT = 14
permission_guard:next_action:DONT_ASK = 2
permission_guard:next_action:EXPLORE = 1
tool_prior:context_policy = 11
tool_prior:executor_kind = 20
tool_prior:model_tier = 24
tool_prior:next_action = 2
```

Negative result:

```text
wrapped_eval_v3_promptctx_safe reached schema/model/context/executor 100.00%
but next_action dropped to 94.40% because the wrapper treated full prompt text
as the mutating action for all variable execution tools. That made global words
such as production/credential in the goal force too many await_human predictions.
The fix is deploy-only prompt-context fallback: use prompt text as action only
when the model omitted action and the inferred tool is deploy_runner.
```

Interpretation:

```text
Stage14 satisfies the larger architecture-policy target: learned model + serving
wrapper reaches 100.00% schema and 100.00% accuracy on all four policy fields
over a 1k native architecture eval slice. This is still an architecture-policy
subplanner/serving-normalization route. It is not a replacement for
LocalAuditPlanner unless the user explicitly asks for runtime integration and a
task-level benchmark validates that integration.
```

## 2026-07-01 Stage15 Runtime-Shadow + Enum-Classifier + Hard-Negative Eval

Goal:

```text
Continue along the five architecture-aligned directions:
1. runtime shadow readiness,
2. low-latency classifier / enum-head path,
3. hard-negative eval,
4. reduced wrapper-rule dependence with measured corrections,
5. Strategist/Architect-compatible policy outputs.
```

New implementation:

```text
scripts/benchmark_architecture_policy_runtime_shadow.py
scripts/benchmark_architecture_policy_classifier.py
scripts/build_architecture_policy_perturbations.py
scripts/architecture_policy.py active-action context extraction
tests/test_openclaw_architecture_policy_shadow.py
tests/test_openclaw_architecture_policy_perturbations.py
```

Low-latency enum classifier, clean 1k:

```text
output: eval_runs/20260701T_stage15_enum_classifier_1k_activeaction
input: processed/openclaw_architecture_stage14_r2_compact_eval.jsonl
rows: 1000
exact_match_rate: 100.00%
model_tier/verifier_next_action/context_policy/executor_kind: 100.00%
mean_prediction_seconds: 0.00005823
```

Compared with learned generation:

```text
Stage14 generation mean_amortized_generation_seconds: 0.149063
Stage15 enum classifier mean_prediction_seconds: 0.00005823
relative speedup on this architecture-policy label task: about 2560x
```

Hard-negative perturbation suite:

```text
processed/stage15_architecture_policy_perturbations_1k.jsonl
rows_written: 3608
types:
  dangerous_action_guard = 304
  expected_next_action_distractor = 1000
  permission_mode_rewrite = 304
  tool_action_distractor = 1000
  tool_name_confusion = 1000
target eval: eval_runs/20260701T_stage15_perturbation_target_eval
target schema/model/next/context/executor: 100.00%
```

Classifier on hard negatives:

```text
before active-action fix:
  output: eval_runs/20260701T_stage15_enum_classifier_perturbations_3608
  exact_match_rate: 92.02%
  failure mode: focused-action context ignored "Perturbation active action" hazard text

after active-action fix:
  output: eval_runs/20260701T_stage15_enum_classifier_perturbations_3608_activeaction
  rows: 3608
  exact_match_rate: 100.00%
  model_tier/verifier_next_action/context_policy/executor_kind: 100.00%
  mean_prediction_seconds: 0.00006395
```

Serving wrapper v6:

```text
wrapped output: eval_runs/20260701T_architecture_policy_model_stage14_r2_1k/wrapped_generations_v6_activeaction.jsonl
eval: eval_runs/20260701T_architecture_policy_model_stage14_r2_1k/wrapped_eval_v6_activeaction
rows: 1000
schema_valid_rate: 100.00%
model_tier_accuracy: 100.00%
next_action_accuracy: 100.00%
context_policy_accuracy: 100.00%
executor_kind_accuracy: 100.00%
```

Runtime shadow matrix, learned raw vs wrapped:

```text
output: eval_runs/20260701T_stage15_runtime_shadow_1k_activeaction
raw rows: 1000
raw schema_valid_rate: 99.90%
raw model/next/context/executor: 97.60% / 93.10% / 98.90% / 98.00%
wrapped schema_valid_rate: 100.00%
wrapped model/next/context/executor: 100.00% / 100.00% / 100.00% / 100.00%
repair_counts:
  model_tier repaired = 24
  next_action repaired = 69
  context_policy repaired = 11
  executor_kind repaired = 20
```

Important design decision:

```text
Do not return to a broad full-prompt dangerous-action guard. Stage14 v3 already
proved that approach over-fires on global goal text. Stage15 uses a narrower
active-action extraction rule:

  Perturbation active action:
  Active action:
  Selected action risk:

Only those explicitly active action/risk lines join the focused title/objective
context. Rejected hard-negative distractors such as "ignore the rejected
alternative action `deploy_runner: run rm -rf ...`" remain ignored.
```

Tests:

```text
/home/litangchao/miniconda3/envs/AgentOpti/bin/python -m unittest discover -s tests -p 'test_openclaw_architecture_policy*.py'
Ran 17 tests: OK
```

Interpretation:

```text
For the architecture-policy subtask, the zero-generation enum classifier is now
the best serving candidate: it matches the 1k clean heldout and 3608-row
hard-negative suite at 100.00% while running in tens of microseconds per row.
The learned generation model remains useful as a distillation target and raw
model signal for shadow diagnostics, but the enum classifier is the safer
application-facing path for runtime shadow logging. This still does not replace
LocalAuditPlanner or the Stage7 command/action planner.
```

## 2026-07-01 Stage16 Shadow Matrix, Tool Hazard, Layer Metrics, Rule Distillation, Stage17 Adapter Pack

Additional implementation:

```text
scripts/benchmark_runtime_shadow_matrix.py
scripts/build_architecture_rule_distillation_sft.py
scripts/build_architecture_adapter_sft.py
scripts/benchmark_architecture_policy_ablation.py
STAGE16_RESULTS_TABLE_CN.md
STAGE17_PRIOR_ABLATION_CN.md
STAGE17_TOOLMAZE_HARD_NEGATIVE_CN.md
STAGE18_NEXT_EXPERIMENTS_CN.md
benchmark_architecture_policy_classifier.py layer metrics:
  strategist = model_tier + verifier_next_action
  architect = context_policy + executor_kind
```

Runtime shadow matrix:

```text
output: eval_runs/20260701T_stage16_runtime_shadow_matrix_1k
rows: 1000
raw exact_match_rate: 89.00%
wrapped exact_match_rate: 100.00%
classifier exact_match_rate: 100.00%
classifier_no_next_prior exact_match_rate: 30.40%
```

Interpretation:

```text
The no-next-prior counterfactual is intentionally bad: exact falls to 30.40%.
This confirms next_action priors / permission guard are still required. The
right route is to distill raw mistakes first, not delete the guard.
```

ToolBench-X style active tool-hazard perturbation:

```text
processed/stage16_architecture_policy_toolhazard_perturbations_1k.jsonl
rows_written: 3912
new type: tool_unreliability_replan = 304
hazards: Specification Drift, Invocation Error, Execution Failure, Output Drift, Cross-source Conflict
target eval: eval_runs/20260701T_stage16_toolhazard_perturbation_target_eval
target schema/model/next/context/executor: 100.00%
```

Classifier result with Strategist/Architect layers:

```text
clean output: eval_runs/20260701T_stage16_enum_classifier_clean1k_layers
clean rows: 1000
clean exact/model/next/context/executor: 100.00%
clean strategist_exact_rate: 100.00%
clean architect_exact_rate: 100.00%
clean mean_prediction_seconds: 0.00006163

toolhazard output: eval_runs/20260701T_stage16_enum_classifier_toolhazard_3912_layers
toolhazard rows: 3912
toolhazard exact/model/next/context/executor: 100.00%
toolhazard strategist_exact_rate: 100.00%
toolhazard architect_exact_rate: 100.00%
toolhazard mean_prediction_seconds: 0.00006568

unsolvable/toolhazard output: eval_runs/20260701T_stage16_enum_classifier_unsolvable_toolhazard_4912_layers
unsolvable/toolhazard rows: 4912
unsolvable/toolhazard exact/model/next/context/executor: 100.00%
unsolvable/toolhazard strategist_exact_rate: 100.00%
unsolvable/toolhazard architect_exact_rate: 100.00%
unsolvable/toolhazard mean_prediction_seconds: 0.00006844
```

Important priority fix:

```text
Active recoverable tool hazard now triggers replan before passive deployment
risk terms trigger await_human. This fixes deploy_runner tool_unreliability
samples where the focused title contains "production deployment" but the active
context is a recoverable tool failure, not a destructive operation.
```

Rule-distillation data:

```text
output: processed/stage16_architecture_rule_distill_classifier_1k.jsonl
summary: processed/stage16_architecture_rule_distill_classifier_1k.summary.json
target eval: eval_runs/20260701T_stage16_rule_distill_classifier_110_target_eval_v2
rows_written: 110
target schema/model/next/context/executor: 100.00%
raw_mismatch_fields:
  verifier_next_action = 69
  model_tier = 24
  executor_kind = 20
  context_policy = 11
```

Stage17 adapter SFT pack:

```text
builder: scripts/build_architecture_adapter_sft.py
output: processed/stage17_architecture_policy_adapter_sft_1k.jsonl
summary: processed/stage17_architecture_policy_adapter_sft_1k.jsonl.summary.json
target eval: eval_runs/20260701T_stage17_architecture_adapter_sft_1k_target_eval
classifier eval: eval_runs/20260701T_stage17_enum_classifier_adapter_1k_layers
rows_written: 1000
source_mix:
  rule_distillation = 110
  perturbation = 890
next_action:
  await_human = 365
  next_subtask = 386
  replan = 249
expected_changed:
  true = 536
  false = 464
target schema/model/next/context/executor: 100.00%
classifier exact/model/next/context/executor: 100.00%
classifier strategist/architect: 100.00%
classifier mean_prediction_seconds: 0.00007283
```

Stage17 ToolMaze implicit semantic failure:

```text
doc: STAGE17_TOOLMAZE_HARD_NEGATIVE_CN.md
new perturbation: implicit_semantic_tool_failure
hard-negative output: processed/stage17_architecture_policy_toolmaze_perturbations_1k.jsonl
hard-negative rows: 5216
implicit_semantic_tool_failure rows: 304
expected_next_action:
  await_human = 1582
  next_subtask = 2646
  replan = 988
target eval: eval_runs/20260701T_stage17_toolmaze_perturbation_target_eval
classifier eval: eval_runs/20260701T_stage17_enum_classifier_toolmaze_5216_layers
classifier exact/strategist/architect: 100.00%
classifier mean_prediction_seconds: 0.00007044
ablation: eval_runs/20260701T_stage17_architecture_policy_ablation_toolmaze_5216
ablation exact:
  full = 100.00%
  no_next_action_prior = 59.97%
  no_tool_priors = 0.00%
  no_permission_guards = 77.53%
  no_hazard_guards = 64.57%
  tool_priors_only = 40.03%
```

Stage17 adapter SFT pack v2:

```text
recommended next training input: processed/stage17_architecture_policy_adapter_sft_toolmaze_1k.jsonl
summary: processed/stage17_architecture_policy_adapter_sft_toolmaze_1k.jsonl.summary.json
target eval: eval_runs/20260701T_stage17_architecture_adapter_sft_toolmaze_1k_target_eval
classifier eval: eval_runs/20260701T_stage17_enum_classifier_adapter_toolmaze_1k_layers
rows_written: 1000
source_mix:
  rule_distillation = 110
  perturbation = 890
next_action:
  await_human = 322
  next_subtask = 348
  replan = 330
expected_changed:
  true = 576
  false = 424
target eval = 100.00%
classifier exact/strategist/architect = 100.00%
classifier mean_prediction_seconds = 0.00007552
```

Stage18 promotion gate:

```text
script: scripts/check_architecture_policy_promotion.py
output: eval_runs/20260701T_stage17_architecture_policy_promotion_gate
adapter_train_ready = pass
runtime_shadow_ready = pass
learned_replacement_ready = fail
recommendation = promote_runtime_shadow_only

input evidence:
  target eval rows = 1000, schema/architecture/verifier/policy exact = 100.00%
  adapter classifier rows = 1000, exact/Strategist/Architect = 100.00%, mean = 0.00007552s
  ToolMaze hard-negative rows = 5216, exact/Strategist/Architect = 100.00%, mean = 0.00007044s
  runtime shadow rows = 860, exact = 100.00%
  ablation no_tool/no_next/no_permission/no_hazard = 0.00% / 59.97% / 77.53% / 64.57%

Interpretation: Stage17 is ready for runtime shadow or guarded wrapper use, but
not for learned replacement. The learned model or adapter must raise ablated
exact rates before any claim that rule/tool/hazard priors are no longer needed.
```

Stage17 prior/guard ablation:

```text
doc: STAGE17_PRIOR_ABLATION_CN.md
clean/native output: eval_runs/20260701T_stage17_architecture_policy_ablation_clean1k
clean/native rows: 1720
clean/native exact:
  full = 100.00%
  no_next_action_prior = 30.93%
  no_tool_priors = 0.00%
  no_permission_guards = 70.00%
  no_hazard_guards = 99.77%
  tool_priors_only = 69.07%

hard-negative output: eval_runs/20260701T_stage17_architecture_policy_ablation_4912
hard-negative rows: 4912
hard-negative exact:
  full = 100.00%
  no_next_action_prior = 57.49%
  no_tool_priors = 0.00%
  no_permission_guards = 76.14%
  no_hazard_guards = 68.57%
  tool_priors_only = 42.51%
```

Interpretation:

```text
Stage16 produces an application-facing architecture-policy stack:
1. runtime shadow matrix for observability,
2. zero-generation classifier for microsecond serving,
3. hard-negative suite that covers danger, distractors, stale hints, recoverable tool hazards, and unsolvable calibrated refusal,
4. Strategist/Architect layer metrics,
5. targeted rule-distillation rows and Stage17 adapter mix to reduce future wrapper dependence.

Do not treat Stage17 target/classifier eval as model improvement by itself. It
only proves the training pack is well-formed. Any adapter trained from it must
return to clean 1k, 4912-row hard-negative, and runtime shadow matrix before
promotion.

The prior/guard ablation proves that tool priors, next_action priors, and
permission guards are still load-bearing. Hazard guards look almost redundant on
clean rows but are essential on hard-negative / unsolvable rows, so they should
remain a hard safety boundary even if future adapters learn the pattern.

The ToolMaze-style implicit semantic failure extension makes this sharper:
no_hazard_guards falls to 64.57% on the 5216-row suite. Use the ToolMaze v2
adapter pack for the next adapter smoke, not the older 4912-only pack.

Stage18 next experiment contract is now written in
STAGE18_NEXT_EXPERIMENTS_CN.md. The recommended order is ToolMaze adapter smoke,
shadow-driven active learning, Tool failure quartet, step router, Agent
Lightning reward bridge, safety enum-head, then Hydra/Medusa JSON-head.
```

2026-07-01 Stage18 ToolMaze adapter training:

```text
doc: STAGE18_TOOLMAZE_ADAPTER_RESULTS_CN.md
new script: scripts/build_architecture_adapter_curriculum.py
new tests: tests/test_openclaw_architecture_adapter_curriculum.py

curriculum data:
  processed/stage18_architecture_policy_adapter_curriculum_2k.jsonl
  rows = 2000
  clean_anchor = 1600
  toolmaze_adapter = 400
  next_subtask / await_human / replan = 1349 / 372 / 279

trained models:
  models/20260701T-stage18-toolmaze-adapter-160
  models/20260701T-stage18-curriculum-adapter-80
  models/20260701T-stage18-curriculum-adapter-20-lr5e6

clean 1k:
  continue200 baseline raw = schema 99.90%, model/next/context/executor 97.60% / 93.10% / 98.90% / 98.00%, mean 0.1491s
  toolmaze-only 160 = schema 100.00%, model/next/context/executor 99.40% / 82.60% / 99.10% / 99.40%, mean 0.1459s
  curriculum 80 = schema 100.00%, model/next/context/executor 97.90% / 88.20% / 98.50% / 99.50%, mean 0.1493s
  curriculum 20/lr5e-6 = schema 99.90%, model/next/context/executor 97.90% / 93.80% / 99.00% / 98.90%, mean 0.1455s

ToolMaze heldout slice, start_line=1001, rows=1000:
  continue200 baseline = schema 94.20%, model/next/context/executor 82.90% / 60.40% / 87.70% / 75.30%, mean 0.1948s
  curriculum 20/lr5e-6 = schema 97.80%, model/next/context/executor 88.90% / 63.60% / 92.70% / 79.40%, mean 0.1814s

Interpretation:
  ToolMaze-only SFT overfits hard-negative labels and hurts clean next_action.
  Clean-anchored curriculum helps, but only very low step / low LR produces a positive result.
  Current best learned candidate is 20260701T-stage18-curriculum-adapter-20-lr5e6/final_adapter.
  It is still not runtime-ready because ToolMaze hard-negative next_action is only 63.60%.
  Keep enum classifier / guarded wrapper as the application path; use the 20-step adapter only as an exploration candidate for enum-head or DPO follow-up.
```
