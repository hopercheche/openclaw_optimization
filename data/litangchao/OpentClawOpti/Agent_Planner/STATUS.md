# Agent Planner Status

Updated: 2026-06-26

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
max_new_tokens: 320
dtype: bf16
attn_implementation: sdpa
device_placement: cuda
sort_by_prompt_length: true
extra_output_policy: compact short-command clamp
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
| batch32, compact policy, 320 tokens | `20260626T104000Z-stage6-transformers-batch32-320-sort-sdpa-cuda-clamp-512gen` | 100.00% | 0.1520 | 0.2298s | 588.63 | current high-reliability default |

The compact policy fixes the residual long-command failure mode where the model starts writing validation scripts such as multiline `python3 -c` checks and hits the generation cap. Raising the cap from 256 to 320 adds only about `0.0013s` versus the compact-policy 256-token check because nearly all examples still stop early. It restores 100% schema validity on 512 examples and keeps latency below the batch16 fallback.

Do not use these attempted shortcuts as defaults:

```text
max_new_tokens=152/160: passed 64 examples but dropped schema on 128 examples
max_new_tokens=224: saves almost nothing and drops schema to 99.61% on 256 examples
dtype=fp16: dropped schema to 92.19% on the 64-example check
max_seq_length=512: dropped schema to 97.66% and lowered command overlap on 128 examples
max_seq_length=704: dropped schema to 98.44% on 128 examples
max_seq_length=960: preserves schema on 256 examples but lowers command overlap to 0.1298
dynamic max-batch-prompt-tokens=32768: preserves schema but slows to 0.2406s on 256 examples
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
7. For speed and reliability, keep the merged model on Transformers batch32 sorted prompts with the compact output policy, SDPA, direct CUDA placement, and a 320-token cap as the current high-reliability serving path. Use batch32/256 without the compact policy as the fastest profile, and batch16 sorted as the lower-memory fallback. Treat vLLM/SGLang as separate validate-and-fallback or serving-stack fine-tuning projects before using either as a direct replacement.
