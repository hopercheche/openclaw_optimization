# Safe Generalization Distill v2 扩展记录（2026-07-08）

## 目标

在上一轮 750 条 safe generalization suite 的基础上继续扩数据，重点补 PhoneHarness 的 safety/mobile affordance 短板，并继续满足：

- 任务必须能在当前 OpenClaw safety/permission runner 下执行。
- 必须有 baseline 对比。
- safety 四项不能回退：invalid tool、hallucinated action、loop failure、unsafe auto allow 必须为 0。

本轮没有调用 Qwen。原因是上一轮失败 taxonomy 已经足够明确：剩余失败集中在 `safety_guard`、`mobile_gui_runner`、`mobile_cli_runner`。因此先用可控模板构造 hard-negative / positive tasks，更容易保证安全可执行。Qwen 更适合下一轮做 paraphrase 和真实语言多样化。

## v2 数据集

复用并扩展：

- 构建脚本：`scripts/build_safe_generalization_distill_suite.py`
- 新增参数：`--phoneharness-expansion-count`

构建命令：

```bash
/home/litangchao/miniconda3/envs/AgentOpti/bin/python scripts/build_safe_generalization_distill_suite.py \
  --phoneharness-expansion-count 250 \
  --output benchmarks/tasks/061_safe_generalization_distill_v2_suite.json \
  --output-dir data/benchmarks/20260708T_safe_generalization_distill_v2_suite
```

输出：

- suite：`benchmarks/tasks/061_safe_generalization_distill_v2_suite.json`
- tasks_dir：`data/benchmarks/20260708T_safe_generalization_distill_v2_suite/tasks_dir`
- summary：`data/benchmarks/20260708T_safe_generalization_distill_v2_suite/summary.json`

结果：

- task_count：1000
- dev / holdout：800 / 200
- 显式 profile/execution hint：0
- safety vetted：true

分来源：

| Source | Tasks |
| --- | ---: |
| TerminalWorld safe-network | 311 |
| PhoneHarness synthetic safety/mobile | 250 |
| tau2 | 184 |
| PhoneHarness original | 144 |
| ToolBench | 100 |
| SkillsBench | 11 |

新增 250 条覆盖：

- safe GUI
- safe CLI / ADB / Termux
- safe MCP
- dual CLI + GUI
- confirm-first GUI / CLI / MCP
- refuse / never-auto GUI / CLI / MCP

## 训练

训练 v2 dev-only profile model：

```bash
/home/litangchao/miniconda3/envs/AgentOpti/bin/python scripts/train_planner_profile_model.py \
  --no-default-generalization \
  --suite data/benchmarks/20260708T_safe_generalization_distill_v2_suite/tasks_dir/061_safe_generalization_distill_v2_suite.json \
  --final-train-split dev \
  --balanced-prior \
  --output data/planner_models/profile_policy_model_safe_distill_v2_dev_20260708.json \
  --metrics-output data/planner_models/profile_policy_metrics_safe_distill_v2_dev_20260708.json \
  --report-output data/planner_models/profile_policy_report_safe_distill_v2_dev_20260708.md
```

训练评估：

- example_count：1000
- final_train_split：dev
- final_example_count：800
- holdout planner_profile_accuracy：98.00%
- holdout execution_tools_accuracy：90.50%
- holdout policy_mode_accuracy：72.50%

注意：classification holdout 的 execution_tools accuracy 不高，所以最终仍以 task-level benchmark 为准。

## Benchmark 对比

三组都跑同一 1000-task suite、同一 `audit_astar`、同一 deterministic runtime。

### 1. 无 profile baseline

```bash
OPENCLAW_DISABLE_PLANNER_PROFILE_MODEL=1 \
/home/litangchao/miniconda3/envs/AgentOpti/bin/python backend/openclaw/benchmark.py \
  --tasks-dir data/benchmarks/20260708T_safe_generalization_distill_v2_suite/tasks_dir \
  --output-dir data/benchmarks/20260708T_safe_generalization_distill_v2_baseline_profile_disabled_astar \
  --strategies audit_astar \
  --repeats 1 \
  --split all \
  --runtime deterministic
```

结果：

- success：47.20%
- holdout：50.50%
- mean latency：1.1544s
- mean search events：86.2300
- safety 四项：0

### 2. v1 prior-best baseline

使用上一轮 750 suite 训练出的模型：

```bash
OPENCLAW_PLANNER_PROFILE_MODEL=data/planner_models/profile_policy_model_safe_distill_dev_20260708.json \
/home/litangchao/miniconda3/envs/AgentOpti/bin/python backend/openclaw/benchmark.py \
  --tasks-dir data/benchmarks/20260708T_safe_generalization_distill_v2_suite/tasks_dir \
  --output-dir data/benchmarks/20260708T_safe_generalization_distill_v2_baseline_v1_distilled_guard_astar \
  --strategies audit_astar \
  --repeats 1 \
  --split all \
  --runtime deterministic
```

结果：

- success：85.50%
- holdout：85.50%
- mean latency：0.6563s
- mean search events：17.4110
- safety 四项：0

分来源关键点：

- 原始 PhoneHarness：118 / 144 = 81.94%
- 新增 synthetic：131 / 250 = 52.40%

说明新增 synthetic 不是“容易样本”，它确实击中了 v1 的 mobile/safety 泛化弱点。

### 3. v2 optimized

```bash
OPENCLAW_PLANNER_PROFILE_MODEL=data/planner_models/profile_policy_model_safe_distill_v2_dev_20260708.json \
/home/litangchao/miniconda3/envs/AgentOpti/bin/python backend/openclaw/benchmark.py \
  --tasks-dir data/benchmarks/20260708T_safe_generalization_distill_v2_suite/tasks_dir \
  --output-dir data/benchmarks/20260708T_safe_generalization_distill_v2_optimized_profile_dev_guarded_astar \
  --strategies audit_astar \
  --repeats 1 \
  --split all \
  --runtime deterministic
```

结果：

- success：97.20%
- holdout：95.00%
- mean_score：0.9951
- mean latency：0.6076s
- mean search events：11.8380
- safety 四项：0

## 总表

| Run | Success | Holdout | Mean latency | Mean search events | Safety violations |
| --- | ---: | ---: | ---: | ---: | ---: |
| profile disabled baseline | 47.20% | 50.50% | 1.1544s | 86.2300 | 0 |
| v1 prior-best baseline | 85.50% | 85.50% | 0.6563s | 17.4110 | 0 |
| v2 distilled | 97.20% | 95.00% | 0.6076s | 11.8380 | 0 |

相对无 profile baseline：

- success +50.00 个百分点
- holdout +44.50 个百分点
- latency 为 baseline 的 52.63%
- search events 为 baseline 的 13.73%

相对 v1 prior-best：

- success +11.70 个百分点
- holdout +9.50 个百分点
- latency 为 v1 的 92.58%
- search events 为 v1 的 67.99%

## v2 分来源结果

| Source | Passed / Tasks | Success |
| --- | ---: | ---: |
| TerminalWorld safe-network | 311 / 311 | 100.00% |
| tau2 | 184 / 184 | 100.00% |
| ToolBench | 100 / 100 | 100.00% |
| SkillsBench | 11 / 11 | 100.00% |
| PhoneHarness synthetic | 250 / 250 | 100.00% |
| PhoneHarness original | 116 / 144 | 80.56% |

剩余失败：

- missing `safety_guard`：17
- missing `mobile_gui_runner`：9
- missing `mobile_cli_runner`：4

v2 的一个小回退：原始 PhoneHarness 从 v1 的 118 / 144 降到 116 / 144。总体收益来自 synthetic safety/mobile 全量修复，但下一轮应该专门针对原始 PhoneHarness 剩余 28 条做更细粒度 hard-negative，而不是继续泛泛扩模板。

## 产物

- v2 suite：`benchmarks/tasks/061_safe_generalization_distill_v2_suite.json`
- v2 suite dir：`data/benchmarks/20260708T_safe_generalization_distill_v2_suite`
- v2 model：`data/planner_models/profile_policy_model_safe_distill_v2_dev_20260708.json`
- v2 comparison：`data/benchmarks/20260708T_safe_generalization_distill_v2_comparison/comparison.json`
- v2 disabled baseline：`data/benchmarks/20260708T_safe_generalization_distill_v2_baseline_profile_disabled_astar`
- v1 prior-best baseline：`data/benchmarks/20260708T_safe_generalization_distill_v2_baseline_v1_distilled_guard_astar`
- v2 optimized：`data/benchmarks/20260708T_safe_generalization_distill_v2_optimized_profile_dev_guarded_astar`

## 结论

v2 是正结果：

- 数据从 750 扩到 1000。
- 新增 250 条 PhoneHarness synthetic safety/mobile 任务。
- 相比 v1 prior-best，在同一 1000-task suite 上 success 从 85.50% 提到 97.20%。
- holdout 从 85.50% 提到 95.00%。
- latency 和 search events 也下降。
- safety 四项全程保持 0。

但它还不是终点：原始 PhoneHarness 仍是主要剩余瓶颈，下一轮应该从 `v2_distilled` 的 28 条原始 PhoneHarness 失败中抽具体 affordance pattern，再做 targeted repair/guard，而不是只继续增加 synthetic 数量。
