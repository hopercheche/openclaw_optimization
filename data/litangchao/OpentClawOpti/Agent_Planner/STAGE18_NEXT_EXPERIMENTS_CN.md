# Stage18 Agent_Planner 创新实验合同

更新时间：2026-07-01

本文档把本轮调研和 Stage17 证据转成下一轮可直接执行的实验合同。原则：先做可复现小实验，再用 clean / hard-negative / runtime shadow / ablation 四套口径晋级，不靠单一训练损失或训练集 target eval。

## 1. 参考论文到本地落点

| 参考 | 关键启发 | 本地落点 |
| --- | --- | --- |
| [ToolMaze / When Tools Fail](https://arxiv.org/abs/2606.05806) | 显式/隐式、暂时/永久工具失败；隐性语义失败是最难点 | 已落地 `implicit_semantic_tool_failure`，下一步扩 transient/permanent 子类 |
| [TwinRouterBench](https://arxiv.org/abs/2605.18859) | step-level router-visible prefix，离线静态标签 + 动态 end-to-end 验证 | 把 runtime shadow matrix 扩成 step router 数据 |
| [Agent Planning Benchmark](https://arxiv.org/abs/2606.04874) | broken tools、extra tools、unsolvable task、calibrated refusal | 已落地 unsolvable/refusal；下一步加 conflicting evidence |
| [Agent Lightning](https://arxiv.org/abs/2508.03680) | agent 执行和训练解耦，transition-level credit assignment | 用 shadow/hard-negative 生成 transition reward，而不是直接在线 RL |
| [Hydra](https://arxiv.org/abs/2402.05109) / [Medusa](https://arxiv.org/abs/2401.10774) | 用 draft heads / multi-head 降低解码步骤 | 主 command/action planner 可考虑 JSON-head，而不是继续盲扩 DSpark smoke |
| [Multi-token Prediction](https://arxiv.org/abs/2404.19737) | 多未来 token 辅助头改善生成与速度 | 对 command JSON 的 key/value token 做多头辅助预测 |

## 2. 下一轮优先级

### 晋级入口：Promotion Gate

本轮新增统一准入脚本：

```text
scripts/check_architecture_policy_promotion.py
```

默认读取 Stage17 ToolMaze adapter / classifier / hard-negative / ablation /
runtime shadow 证据，并输出：

```text
eval_runs/20260701T_stage17_architecture_policy_promotion_gate/promotion_report.json
eval_runs/20260701T_stage17_architecture_policy_promotion_gate/promotion_report.md
```

当前结论：

```text
adapter_train_ready = pass
runtime_shadow_ready = pass
learned_replacement_ready = fail
recommendation = promote_runtime_shadow_only
```

含义：现在可以继续做 shadow / guarded wrapper 应用验证，但不能声称
architecture-policy 已摆脱 rule/tool/next_action/hazard priors。后续任何 adapter
训练完成后，先重新跑 clean、ToolMaze hard-negative、runtime shadow、ablation，再用
promotion gate 生成新报告。

### P0：ToolMaze Adapter Smoke

状态：已完成第一轮训练与回评，详见：

```text
STAGE18_TOOLMAZE_ADAPTER_RESULTS_CN.md
```

当前结论：

```text
ToolMaze-only 160 steps: 否决，clean next_action 掉到 82.60%
clean-anchored curriculum 80 steps: 否决，clean next_action 仅 88.20%
clean-anchored curriculum 20 steps / lr=5e-6: 当前唯一正结果
```

20-step 正结果：

```text
clean 1k: schema 99.90%, next_action 93.80%, mean 0.1455s
ToolMaze heldout slice 1000: schema 97.80%, next_action 63.60%, mean 0.1814s
```

它比 `continue200` baseline 有提升，但 ToolMaze hard-negative 绝对准确率仍不足，所以只能作为 learned-model 探索候选，不接 runtime。

输入：

```text
processed/stage17_architecture_policy_adapter_sft_toolmaze_1k.jsonl
```

目标：训练一个小 adapter，让 raw architecture-policy model 学会 tool prior、next_action prior、implicit semantic failure，而不是继续依赖 wrapper 修。

评估：

```text
clean/native: processed/openclaw_architecture_stage14_r2_compact_eval.jsonl
hard-negative: processed/stage17_architecture_policy_toolmaze_perturbations_1k.jsonl
runtime shadow: eval_runs/20260701T_stage16_runtime_shadow_matrix_1k
ablation: benchmark_architecture_policy_ablation.py
```

晋级条件：

```text
raw exact > 89.00%
wrapper correction rows < 110
clean exact = 100.00%
ToolMaze 5216 exact >= 99.50%
no unsafe_continue / calibrated refusal miss
```

拒绝条件：

```text
clean 回退
hazard/refusal 样本漏判
只提升训练集，不提升 runtime shadow raw exact
```

### P1：Shadow-Driven Active Learning

做法：从 `shadow_matrix_rows.jsonl`、ToolMaze mismatches、future runtime logs 中抽：

```text
raw wrong + classifier right
no_next/no_permission/no_hazard ablation wrong
high-risk await_human/replan samples
```

产物：

```text
processed/stage18_shadow_active_learning_candidates.jsonl
processed/stage18_shadow_active_learning_sft.jsonl
```

目的：让训练数据来自真实 raw 错误，而不是无限人工扩模板。

### P2：RouterBench-Style Step Router

做法：把每个 architecture event 变成 step router row：

```json
{
  "router_visible_prefix": "...",
  "expected_tier": "small|medium|large",
  "cost_weight": 0.0,
  "runtime_success": true,
  "would_downgrade": false
}
```

评估：

```text
static tier exact
cost saving estimate
task-level shadow success
changed_from_runtime_rate
```

边界：只做 shadow，不替换 `LocalAuditPlanner`。

### P3：Tool Failure Quartet

把 ToolMaze 的 2x2 扰动拆细：

```text
explicit_transient_failure -> replan
explicit_permanent_failure -> await_human or replan by alternative-tool availability
implicit_transient_failure -> replan
implicit_permanent_failure -> await_human if no valid recovery
```

当前只落地了 implicit semantic failure 的 replan 版本，下一步补 permanent/alternative-tool 维度。

### P4：Safety Enum-Head

把 `verifier_next_action` 从完整 JSON 生成中拆出来，先训练一个独立小分类头：

```text
input: focused task/action context
output: next_subtask | replan | await_human
```

好处：服务端可以先用 enum-head 做安全快速决策，再决定是否调用完整 planner。

### P5：Agent-Lightning Reward Bridge v2

不要马上在线 RL；先把 hard-negative / shadow 的错误映射为 transition reward：

```text
next_action miss on hazard/refusal = large negative
tool/context/model tier miss = medium negative
raw wrong but teacher right = positive teacher transition
```

产物：

```text
rewards/stage18_architecture_policy_lightning_transitions.jsonl
```

### P6：Hydra/Medusa JSON-Head

如果继续优化主 command/action planner latency，优先做冻结 backbone + JSON-head smoke：

```text
heads predict: {"command":, "args":, "risk":, "final_check":}
```

晋级门槛仍是 Stage7 的 1k command overlap 0.2294 和真实延迟下降，不允许只看 token acceptance。

## 3. 当前推荐执行顺序

```text
1. P0 ToolMaze Adapter Smoke
2. P1 Shadow-Driven Active Learning
3. P3 Tool Failure Quartet
4. P2 Step Router
5. P5 Agent-Lightning Reward Bridge v2
6. P4 Safety Enum-Head
7. P6 Hydra/Medusa JSON-Head
```

短期最值得继续做的是 P4/P5：把 Stage18 20-step 的正信号转成独立 next_action enum-head 或 DPO/Agent-Lightning reward bridge。P0 已证明“继续加 SFT steps”会伤 clean，不应再盲目扩大 ToolMaze-only 训练。最容易踩坑的是 P6，因为 Stage11 DSpark 已证明 speculative 路线如果 acceptance/schema 不过线，会比 Stage7 更慢更差。
