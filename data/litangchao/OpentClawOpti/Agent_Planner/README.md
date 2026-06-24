# Agent Planner Training Track

This folder is an independent training track for a fast, high-accuracy agent planner. It does not reuse the existing `backend/openclaw/planner.py` orchestration path.

## Goal

Train a planner policy that maps:

```text
goal + state + available tools + constraints -> next action / short plan / ask / refuse
```

The model should optimize for:

- low latency
- high task success
- valid tool selection
- low loop/hallucination rate
- safe permission behavior

## Mature Route

Recommended route:

1. Use **ToolBench** as the primary public tool-planning corpus.
2. Use **AgentScope 2.0** as the runtime shell because it already has event, permission, sandbox, middleware, and task-planning abstractions.
3. Use **Agent Lightning** as the RL/reward-training interface direction, where AgentScope executions are treated as trajectories and verifier outputs become rewards.
4. Use an automatic verifier rather than manual labels:
   - success/failure
   - invalid tool call
   - missing required tool
   - policy violation
   - loop/repeated action
   - unsafe auto-allow

This gives a practical two-stage path:

```text
SFT warm start on ToolBench-like trajectories
-> AgentScope rollout collection
-> verifier/reward filtering
-> Agent Lightning RL or preference optimization
```

## Selected Data

Primary large dataset:

- `LLM-OS-Models/Qwen-Terminal-ToolBench-Processed-Tokenized`
- Selected subset: `qwen35_2b_full_terminal_toolcall_processed_v1`
- Rows: 1,011,776
- Reported subset size: 36.26 GiB
- License: Apache-2.0
- Reason: large enough for SFT, below the 50G constraint, already processed for terminal/tool-call training.

Supporting interpretable dataset:

- `tuandunghcmut/toolbench-v1`
- Repo storage: about 0.54 GB
- Size category: 100K to 1M examples
- License: Apache-2.0
- Reason: closer to original ToolBench/ToolLLaMA semantics and useful for schema inspection.

Optional reward/evaluation trajectories:

- `AgentSuite/tau-bench-trajectories`
- Reason: real per-model agent trajectories with `messages` and `eval_result`, useful for reward modeling and automatic filtering experiments.

## Paths

```text
raw/        downloaded source datasets
processed/  normalized planner training JSONL
rewards/    verifier and reward labels
models/     local checkpoints or adapters
configs/    route and dataset manifests
scripts/    download and preprocessing utilities
```

## Quick Start

Dry-run the primary subset:

```bash
python data/litangchao/OpentClawOpti/Agent_Planner/scripts/download_hf_subset.py \
  --source qwen_terminal_toolbench_2b_full \
  --target-root data/litangchao/OpentClawOpti/Agent_Planner/raw \
  --dry-run
```

Download only the final Arrow dataset files, skipping intermediate cache files:

```bash
python data/litangchao/OpentClawOpti/Agent_Planner/scripts/download_hf_subset.py \
  --source qwen_terminal_toolbench_2b_full \
  --target-root data/litangchao/OpentClawOpti/Agent_Planner/raw
```

Download the smaller ToolBench source first if bandwidth is limited:

```bash
python data/litangchao/OpentClawOpti/Agent_Planner/scripts/download_hf_subset.py \
  --source toolbench_v1 \
  --target-root data/litangchao/OpentClawOpti/Agent_Planner/raw
```

## Notes

- The full Qwen terminal/toolbench repository is about 77 GB, so do not clone the whole repo.
- The downloader filters to one dataset subfolder and skips `cache-*.arrow` by default.
- Install `datasets`, `pyarrow`, `transformers`, `peft`, `trl`, `accelerate`, and `agentscope` in `AgentOpti` before actual training.
- The official package name is `agentlightning`, not `agent-lightning`. The GitHub source is cloned at `external/agent-lightning` and installed into `AgentOpti` in editable mode. The local bridge also emits Agent-Lightning-style transition JSONL for the existing tau-bench reward data.

Build Agent-Lightning-style transitions from tau-bench reward examples:

```bash
/home/litangchao/miniconda3/bin/conda run -n AgentOpti python \
  data/litangchao/OpentClawOpti/Agent_Planner/scripts/build_agent_lightning_transitions.py \
  --input data/litangchao/OpentClawOpti/Agent_Planner/rewards/tau_bench_rewards.jsonl \
  --output data/litangchao/OpentClawOpti/Agent_Planner/rewards/tau_bench_agent_lightning_transitions.jsonl \
  --credit final
```
