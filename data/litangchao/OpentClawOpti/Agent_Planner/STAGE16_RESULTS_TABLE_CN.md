# Stage16 Agent_Planner 优化结果表

更新时间：2026-07-01

本文档记录 Stage16 已落地的 runtime shadow、enum classifier、hard-negative、rule-distillation、Strategist/Architect 分层结果。所有结果仍限定在 `Agent_Planner` architecture-policy/shadow 路线，不替换 `backend/openclaw/planner.py`。

## 1. 核心指标

| 路线 | 产物 | 样本 | 核心结果 | 延迟/成本 | 结论 |
| --- | --- | ---: | --- | --- | --- |
| Stage14 learned raw | `eval_runs/20260701T_architecture_policy_model_stage14_r2_1k/raw_eval` | 1000 | schema 99.90%，model/next/context/executor = 97.60%/93.10%/98.90%/98.00% | generation mean 0.149063s | raw model 不能直接接 runtime |
| Stage15 wrapper v6 | `eval_runs/20260701T_architecture_policy_model_stage14_r2_1k/wrapped_eval_v6_activeaction` | 1000 | schema 与四个 policy 字段均 100.00% | wrapper rule 修复 110 个 raw field errors | 可作为 serving-normalization / shadow 层 |
| Stage15 enum classifier clean | `eval_runs/20260701T_stage15_enum_classifier_1k_activeaction` | 1000 | exact 100.00%，四字段 100.00% | mean 0.00005823s | 当前 architecture-policy 最快应用路径 |
| Stage15 hard-negative active-action | `eval_runs/20260701T_stage15_enum_classifier_perturbations_3608_activeaction` | 3608 | exact 100.00%，四字段 100.00% | mean 0.00006395s | 修复了 focused-action 漏检 active hazard 的问题 |
| Stage16 ToolBench-X 风格 hazard | `eval_runs/20260701T_stage16_enum_classifier_toolhazard_3912_layers` | 3912 | exact 100.00%，Strategist/Architect 均 100.00% | mean 0.00006568s | 新增 recoverable tool hazard -> replan |
| Stage16 APB 风格 unsolvable/refusal | `eval_runs/20260701T_stage16_enum_classifier_unsolvable_toolhazard_4912_layers` | 4912 | exact 100.00%，Strategist/Architect 均 100.00% | mean 0.00006844s | 新增 unsolvable task -> await_human |
| Stage16 runtime shadow matrix | `eval_runs/20260701T_stage16_runtime_shadow_matrix_1k` | 1000 | raw exact 89.00%，wrapped/classifier exact 100.00%，no-next-prior exact 30.40% | 非生成诊断 | next_action prior 不能删；shadow matrix 可接应用日志 |
| Stage16 rule distillation | `processed/stage16_architecture_rule_distill_classifier_1k.jsonl` | 110 | target eval 四字段 100.00% | 从 raw 错误中抽取 | 用于后续减少 wrapper-rule 依赖的 SFT 小包 |
| Stage17 adapter SFT mix | `processed/stage17_architecture_policy_adapter_sft_1k.jsonl` | 1000 | target eval 100.00%，classifier exact 100.00% | classifier mean 0.00007283s | 110 raw-mistake + 890 hard-negative，下一轮 adapter 小训输入 |
| Stage17 prior/guard ablation | `STAGE17_PRIOR_ABLATION_CN.md` | 1720 + 4912 | clean no-next 30.93%，hard no-hazard 68.57%，no-tool 0.00% | 非生成诊断 | tool/next/permission prior 可蒸馏；hazard guard 继续硬保留 |
| Stage17 ToolMaze implicit failure | `STAGE17_TOOLMAZE_HARD_NEGATIVE_CN.md` | 5216 | target/classifier exact 100.00%，no-hazard 64.57% | classifier mean 0.00007044s | 新增 implicit semantic failure，当前推荐 hard-negative 口径 |
| Stage17 adapter SFT ToolMaze | `processed/stage17_architecture_policy_adapter_sft_toolmaze_1k.jsonl` | 1000 | target/classifier exact 100.00%，replan 330 | classifier mean 0.00007552s | 当前推荐 adapter 小训输入 |

## 2. 新增 hard-negative 类型

| 类型 | 数量 | 期望行为 | 来源思想 |
| --- | ---: | --- | --- |
| `dangerous_action_guard` | 304 | active 危险动作 -> `await_human` | safety guard |
| `tool_unreliability_replan` | 304 | recoverable tool hazard -> `replan` | ToolBench-X 五类 hazard |
| `implicit_semantic_tool_failure` | 304 | corrupted tool output / stale success signal -> `replan` | ToolMaze 隐性语义失败 |
| `unsolvable_task_refusal` | 1000 | no valid recovery path / missing required data -> `await_human` | Agent Planning Benchmark calibrated refusal |
| `permission_mode_rewrite` | 304 | permission mode 改写后 next_action 跟随 guard | runtime permission policy |
| `tool_action_distractor` | 1000 | rejected dangerous distractor 不应污染当前 subtask | hard-negative robustness |
| `tool_name_confusion` | 1000 | stale tool name 不应覆盖 selected tool | tool confusion robustness |
| `expected_next_action_distractor` | 1000 | stale expected_next_action 不应覆盖 active label | verifier-hint robustness |

生成文件：

```text
processed/stage16_architecture_policy_toolhazard_perturbations_1k.jsonl
processed/stage16_architecture_policy_toolhazard_perturbations_1k.summary.json
processed/stage16_architecture_policy_unsolvable_toolhazard_perturbations_1k.jsonl
processed/stage16_architecture_policy_unsolvable_toolhazard_perturbations_1k.summary.json
processed/stage17_architecture_policy_toolmaze_perturbations_1k.jsonl
processed/stage17_architecture_policy_toolmaze_perturbations_1k.jsonl.summary.json
```

## 3. Runtime Shadow Matrix 读法

产物：

```text
eval_runs/20260701T_stage16_runtime_shadow_matrix_1k/shadow_matrix_rows.jsonl
eval_runs/20260701T_stage16_runtime_shadow_matrix_1k/metrics.json
eval_runs/20260701T_stage16_runtime_shadow_matrix_1k/report.md
```

每行并排记录：

```text
raw learned model
wrapped serving policy
zero-generation classifier
classifier_no_next_prior counterfactual
expected runtime policy
wrapper_rules
would_change_runtime
```

关键发现：

```text
raw exact = 89.00%
wrapped exact = 100.00%
classifier exact = 100.00%
classifier_no_next_prior exact = 30.40%
```

解释：`next_action` prior/permission guard 现在仍是必要安全组件，不能为了“减少规则”直接删除。更合理的路线是把 wrapper 修复样本蒸馏给模型，逐步减少 raw 错误率，再用 shadow matrix 验证规则依赖是否下降。

## 4. Rule Distillation 数据包

产物：

```text
processed/stage16_architecture_rule_distill_classifier_1k.jsonl
processed/stage16_architecture_rule_distill_classifier_1k.summary.json
eval_runs/20260701T_stage16_rule_distill_classifier_110_target_eval_v2
```

抽取条件：

```text
raw learned model exact = false
classifier exact = true
```

数量与错误字段：

```text
rows_written = 110
raw_mismatch_fields:
  verifier_next_action = 69
  model_tier = 24
  executor_kind = 20
  context_policy = 11
```

这不是替代主模型的训练集，而是下一轮 architecture-policy adapter 的 targeted correction set。

## 5. Stage17 Adapter 数据包

产物：

```text
processed/stage17_architecture_policy_adapter_sft_1k.jsonl
processed/stage17_architecture_policy_adapter_sft_1k.jsonl.summary.json
eval_runs/20260701T_stage17_architecture_adapter_sft_1k_target_eval
eval_runs/20260701T_stage17_enum_classifier_adapter_1k_layers
scripts/build_architecture_adapter_sft.py
```

组成：

```text
rows_written = 1000
source_mix:
  rule_distillation = 110
  perturbation = 890
perturbation_type_counts:
  dangerous_action_guard = 128
  expected_next_action_distractor = 127
  permission_mode_rewrite = 127
  rule_distillation = 110
  tool_action_distractor = 127
  tool_name_confusion = 127
  tool_unreliability_replan = 127
  unsolvable_task_refusal = 127
next_action:
  await_human = 365
  next_subtask = 386
  replan = 249
expected_changed:
  true = 536
  false = 464
```

验证：

```text
target eval: schema/model/next/context/executor = 100.00%
classifier eval: exact/model/next/context/executor = 100.00%
strategist_exact_rate = 100.00%
architect_exact_rate = 100.00%
mean_prediction_seconds = 0.00007283
```

解释：Stage17 不是“在训练集上宣布成功”，而是把 Stage16 的 110 条真实 raw 错误修复样本扩成一个可训练、可复现、分布相对均衡的 adapter 小训包。下一步训练后必须回到 clean 1k、4912 hard-negative、runtime shadow matrix 三套评估。

## 6. 论文/开源映射

| 方向 | 参考 | 本地落点 |
| --- | --- | --- |
| step-level routing | [TwinRouterBench](https://arxiv.org/abs/2605.18859) | runtime shadow matrix、no-next-prior counterfactual、per-step classifier |
| planning diagnostics | [Agent Planning Benchmark](https://arxiv.org/abs/2606.04874) | hard-negative / broken-tool / unsolvable-task eval |
| large tool ecosystem robustness | [PlanBench-XL](https://arxiv.org/abs/2606.22388) | missing/failing/distracting tool perturbations |
| tool unreliability | [ToolBench-X](https://arxiv.org/abs/2606.25819) / [GitHub](https://github.com/Foreverskyou/ToolBench-X) | `tool_unreliability_replan` 五类 hazard |
| agent RL transition | [Agent Lightning](https://arxiv.org/abs/2508.03680) | transition reward 分解和后续 rule-distillation/RLVR |
| speculative / multi-head acceleration | [Medusa](https://arxiv.org/abs/2401.10774), [Hydra](https://arxiv.org/abs/2402.05109) | Stage11/未来 enum-head 或 command JSON heads |

## 7. 下一轮推荐

1. 把 `benchmark_runtime_shadow_matrix.py` 变成 runtime shadow logger 的离线/在线共用格式，但默认只记录不改决策。
2. 在 `stage17_architecture_policy_adapter_sft_toolmaze_1k.jsonl` 上做 adapter 小训 smoke，但晋级必须同时过 clean 1k、5216 ToolMaze hard-negative、runtime shadow matrix。
3. 继续扩大 ToolBench-X/APB 风格扰动：增加 silent failure、conflicting evidence、blocked path、multi-tool contradictory evidence。
4. 用 `benchmark_architecture_policy_ablation.py` 跟踪 prior/guard 依赖；只有 no-next-prior、no-permission-guard 在 clean 与 hard-negative 上都明显提升后，才考虑把对应规则从硬规则降级为模型先验。
5. 若继续加速主 command/action planner，优先评估 Medusa/Hydra 风格 JSON-head，而不是继续扩大 DSpark 20-step smoke。
