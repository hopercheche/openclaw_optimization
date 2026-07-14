# Stage17 ToolMaze 式隐性工具失败优化

更新时间：2026-07-01

本轮在 ToolBench-X 五类工具异常之外，参考 ToolMaze / dynamic replanning 的思路，增加 `implicit_semantic_tool_failure`：工具调用看似成功，但输出语义被污染或 success signal 已过期，planner 必须 `replan`，不能继续信任结果。

参考：

```text
When Tools Fail / ToolMaze: https://arxiv.org/abs/2606.05806
ToolBench-X: https://arxiv.org/abs/2606.25819
Agent Planning Benchmark: https://arxiv.org/abs/2606.04874
```

## 1. 新增代码

```text
scripts/architecture_policy.py
scripts/build_architecture_policy_perturbations.py
tests/test_openclaw_architecture_policy_shadow.py
tests/test_openclaw_architecture_policy_perturbations.py
```

新增扰动类型：

```text
implicit_semantic_tool_failure
```

触发文本：

```text
implicit semantic failure
semantic anomaly
corrupted output
corrupted tool output
stale success signal
transient failure
permanent failure
```

期望行为：

```text
variable execution tools -> verifier_next_action = replan
```

## 2. 新 hard-negative 套件

产物：

```text
processed/stage17_architecture_policy_toolmaze_perturbations_1k.jsonl
processed/stage17_architecture_policy_toolmaze_perturbations_1k.jsonl.summary.json
eval_runs/20260701T_stage17_toolmaze_perturbation_target_eval
eval_runs/20260701T_stage17_enum_classifier_toolmaze_5216_layers
eval_runs/20260701T_stage17_architecture_policy_ablation_toolmaze_5216
```

生成统计：

```text
base rows = 1000
rows_written = 5216
perturbation_counts:
  dangerous_action_guard = 304
  expected_next_action_distractor = 1000
  implicit_semantic_tool_failure = 304
  permission_mode_rewrite = 304
  tool_action_distractor = 1000
  tool_name_confusion = 1000
  tool_unreliability_replan = 304
  unsolvable_task_refusal = 1000
expected_next_action:
  await_human = 1582
  next_subtask = 2646
  replan = 988
```

评估结果：

```text
target eval:
  schema/model/next/context/executor = 100.00%

classifier eval:
  exact/model/next/context/executor = 100.00%
  strategist_exact_rate = 100.00%
  architect_exact_rate = 100.00%
  mean_prediction_seconds = 0.00007044
```

消融结果：

```text
full = 100.00%
no_next_action_prior = 59.97%
no_tool_priors = 0.00%
no_permission_guards = 77.53%
no_hazard_guards = 64.57%
tool_priors_only = 40.03%
```

解释：加入隐性语义失败后，`no_hazard_guards` 从 4912 套件的 68.57% 进一步降到 64.57%，说明 hazard guard 对“看似成功但语义污染”的工具输出尤其关键。

## 3. Adapter v2

产物：

```text
processed/stage17_architecture_policy_adapter_sft_toolmaze_1k.jsonl
processed/stage17_architecture_policy_adapter_sft_toolmaze_1k.jsonl.summary.json
eval_runs/20260701T_stage17_architecture_adapter_sft_toolmaze_1k_target_eval
eval_runs/20260701T_stage17_enum_classifier_adapter_toolmaze_1k_layers
```

组成：

```text
rows_written = 1000
source_mix:
  rule_distillation = 110
  perturbation = 890
perturbation_type_counts:
  dangerous_action_guard = 112
  expected_next_action_distractor = 112
  implicit_semantic_tool_failure = 111
  permission_mode_rewrite = 111
  rule_distillation = 110
  tool_action_distractor = 111
  tool_name_confusion = 111
  tool_unreliability_replan = 111
  unsolvable_task_refusal = 111
next_action:
  await_human = 322
  next_subtask = 348
  replan = 330
expected_changed:
  true = 576
  false = 424
```

验证：

```text
target eval = 100.00%
classifier exact = 100.00%
strategist/architect = 100.00%
mean_prediction_seconds = 0.00007552
```

结论：`stage17_architecture_policy_adapter_sft_toolmaze_1k.jsonl` 比上一版 adapter 更适合作为下一轮小训输入，因为它覆盖了显式工具失败、隐性语义失败、不可解任务、危险动作和 distractor。
