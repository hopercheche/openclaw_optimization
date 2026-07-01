# Stage17 Architecture-Policy Prior/Guard 消融结果

更新时间：2026-07-01

本文档记录本轮新增的细粒度 prior/guard 消融，用来判断哪些 wrapper/classifier 组件可以被蒸馏，哪些必须继续保留为安全边界。

## 1. 产物

```text
scripts/benchmark_architecture_policy_ablation.py
eval_runs/20260701T_stage17_architecture_policy_ablation_clean1k/
eval_runs/20260701T_stage17_architecture_policy_ablation_4912/
tests/test_openclaw_architecture_policy_ablation.py
```

注意：`clean1k` 目录名沿用了 clean 口径，但实际输入是 `processed/openclaw_architecture_stage14_r2_compact_eval.jsonl` 的 1720 条 native architecture rows。

## 2. 总体结果

| 输入 | rows | full | no_next_action_prior | no_tool_priors | no_permission_guards | no_hazard_guards | tool_priors_only |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| native clean | 1720 | 100.00% | 30.93% | 0.00% | 70.00% | 99.77% | 69.07% |
| hard-negative + unsolvable | 4912 | 100.00% | 57.49% | 0.00% | 76.14% | 68.57% | 42.51% |

字段级结论：

```text
no_tool_priors:
  model_tier/context_policy/executor_kind 均为 0.00%，说明工具先验仍是结构字段主支撑。

no_next_action_prior:
  clean exact 30.93%，hard-negative exact 57.49%，说明 next_action prior 仍不能删除。

no_permission_guards:
  clean exact 70.00%，hard-negative exact 76.14%，说明 permission mode 仍承担大量 next_action 分流。

no_hazard_guards:
  clean exact 99.77%，hard-negative exact 68.57%，说明 hazard guard 在 clean 集不显眼，但在对抗/不可解任务上是关键安全边界。
```

## 3. 决策

1. 不要把 “删掉 wrapper rule” 作为短期目标；当前证据显示删 prior/guard 会显著回退。
2. 可以把 tool prior 和 next_action prior 作为 Stage18 adapter 的蒸馏目标，因为它们影响大量普通样本。
3. hazard guard 不应被模型完全替代；即使训练后模型能学到，也要保留为最后安全边界。
4. permission guard 可以尝试软蒸馏，但 runtime 接入前必须继续硬保留。
5. 下一轮训练后的晋级评估必须同时报告：

```text
clean/native exact
4912 hard-negative exact
runtime shadow raw/wrapped/classifier/no-prior matrix
prior/guard ablation table
unsafe_continue_rate
calibrated_refusal_rate
```

## 4. 下一步创新点

| 创新点 | 可执行实验 | 晋级条件 |
| --- | --- | --- |
| Prior-aware adapter distillation | 用 `stage17_architecture_policy_adapter_sft_1k.jsonl` 小训，让 raw model 学会 tool/next prior | raw exact 从 89.00% 提升，wrapper correction 下降，clean/hard-negative 不回退 |
| Guard-aware loss weighting | 对 expected_changed=true、await_human、replan 样本加权 | hazard/refusal 样本不漏判，clean exact 不降 |
| Counterfactual consistency training | 同一 subtask 生成 full/no-next/no-hazard 对照样本 | no-prior ablation 的 exact 提升，但 hard guard 仍保留 |
| Shadow-driven active learning | 从 runtime shadow matrix 抽取 raw wrong / classifier right / high-risk rows | 新增 correction rows 后 raw_mismatch_fields 分布收敛 |
| Safety-head / enum-head split | 将 next_action 作为独立小 head 或分类器，不走完整 JSON 生成 | 微秒级延迟，hard-negative exact 不低于当前 classifier |
