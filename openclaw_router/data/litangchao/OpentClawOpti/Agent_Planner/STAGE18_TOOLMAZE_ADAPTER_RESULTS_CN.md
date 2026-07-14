# Stage18 ToolMaze Adapter 训练结果

更新时间：2026-07-01

## 结论

本轮尝试了三条 ToolMaze adapter 训练路线：

1. `ToolMaze-only 160 steps`：失败。clean 1k 上 `next_action_accuracy` 从上一版 raw 93.10% 掉到 82.60%，模型过度保守，明显把普通 clean 任务误判成 `replan`。
2. `clean-anchored curriculum 80 steps`：部分恢复但仍失败。clean 1k `next_action_accuracy` 回到 88.20%，仍低于上一版 raw 93.10%。
3. `clean-anchored curriculum 20 steps / lr=5e-6`：当前唯一正结果。clean 1k 略优于上一版 raw，ToolMaze heldout slice 也优于旧 adapter，但 hard-negative 绝对值仍不足以晋级 learned replacement。

因此，Stage18 的下一步应沿“低步数、低学习率、clean anchor + 少量 hard-negative”的 curriculum 继续，而不是扩大 ToolMaze-only 训练。

## 数据与模型

新增 curriculum builder：

```text
scripts/build_architecture_adapter_curriculum.py
```

新增训练数据：

```text
processed/stage18_architecture_policy_adapter_curriculum_2k.jsonl
processed/stage18_architecture_policy_adapter_curriculum_2k.jsonl.summary.json
```

数据分布：

```text
rows = 2000
clean_anchor = 1600
toolmaze_adapter = 400
next_action:
  next_subtask = 1349
  await_human = 372
  replan = 279
expected_changed = 229
```

新增模型：

```text
models/20260701T-stage18-toolmaze-adapter-160
models/20260701T-stage18-curriculum-adapter-80
models/20260701T-stage18-curriculum-adapter-20-lr5e6
```

当前推荐候选仅为：

```text
models/20260701T-stage18-curriculum-adapter-20-lr5e6/final_adapter
```

## Clean 1k 对比

| 模型 | schema | model_tier | next_action | context_policy | executor_kind | mean seconds | 结论 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Stage14/continue200 raw baseline | 99.90% | 97.60% | 93.10% | 98.90% | 98.00% | 0.1491 | 基线 |
| Stage18 ToolMaze-only 160 | 100.00% | 99.40% | 82.60% | 99.10% | 99.40% | 0.1459 | 失败，过度 replan |
| Stage18 curriculum 80 | 100.00% | 97.90% | 88.20% | 98.50% | 99.50% | 0.1493 | 未恢复 |
| Stage18 curriculum 20/lr5e-6 | 99.90% | 97.90% | 93.80% | 99.00% | 98.90% | 0.1455 | 当前最佳 learned 候选 |

对应路径：

```text
eval_runs/20260701T_stage18_toolmaze_adapter160_clean1k_scored
eval_runs/20260701T_stage18_curriculum_adapter80_clean1k_scored
eval_runs/20260701T_stage18_curriculum_adapter20_clean1k_scored
```

## ToolMaze heldout slice 对比

评估切片：

```text
processed/stage17_architecture_policy_toolmaze_perturbations_1k.jsonl
start_line = 1001
generation_examples = 1000
```

| 模型 | schema | model_tier | next_action | context_policy | executor_kind | mean seconds | 结论 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Stage14/continue200 baseline | 94.20% | 82.90% | 60.40% | 87.70% | 75.30% | 0.1948 | hard-negative 明显不足 |
| Stage18 curriculum 20/lr5e-6 | 97.80% | 88.90% | 63.60% | 92.70% | 79.40% | 0.1814 | 全字段提升，但仍不足晋级 |

对应路径：

```text
eval_runs/20260701T_stage18_baseline_continue200_toolmaze_1001_1000_scored
eval_runs/20260701T_stage18_curriculum_adapter20_toolmaze_1001_1000_scored
```

## 解释

ToolMaze-only 训练失败的原因不是 GPU 或训练脚本，而是标签分布与 clean runtime 分布冲突：

```text
ToolMaze adapter 1k:
  await_human = 322
  next_subtask = 348
  replan = 330

clean eval 1k:
  await_human = 80
  next_subtask = 882
  replan = 38
```

直接训练会把模型推向“看到风险提示就 replan/await_human”，导致 clean runtime 上过度保守。curriculum 20-step 说明少量 hard-negative 信号有用，但 learned model 还没有学会稳定的 hazard/refusal 边界。

## 下一步

1. 保留 `stage18-curriculum-adapter-20-lr5e6` 作为探索候选，不接 runtime。
2. 继续做更细粒度的 next_action enum-head 或 DPO，而不是继续 SFT 加步数。
3. 对 ToolMaze `await_human` 失败样本单独做 refusal/hazard 分类头；当前 learned model 在 small/medium `await_human` 上仍弱。
4. promotion gate 仍应维持 `learned_replacement_ready=fail`，直到 hard-negative 1k/5k 的 schema 和 next_action 接近 classifier 水平。
