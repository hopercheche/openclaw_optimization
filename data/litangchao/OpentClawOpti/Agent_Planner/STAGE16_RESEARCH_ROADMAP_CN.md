# Stage16 OpenClaw Agent_Planner 后续创新优化调研与落地路线

更新时间：2026-07-01

本文档只记录 `Agent_Planner` 后续研究路线和可执行实验合同，不修改 `AGENTS.md`、`STATUS.md` 或 runtime planner。所有新实验建议继续放在：

```text
data/litangchao/OpentClawOpti/Agent_Planner/
```

默认环境仍是：

```text
CUDA_VISIBLE_DEVICES=1
/home/litangchao/miniconda3/envs/AgentOpti/bin/python
```

## 0.1 本轮已落地结果

2026-07-01 已把 Stage16/17 从路线设计推进到六个可复现产物：

```text
scripts/benchmark_runtime_shadow_matrix.py
scripts/build_architecture_rule_distillation_sft.py
scripts/build_architecture_adapter_sft.py
scripts/benchmark_architecture_policy_ablation.py
processed/stage16_architecture_policy_toolhazard_perturbations_1k.jsonl
processed/stage16_architecture_policy_unsolvable_toolhazard_perturbations_1k.jsonl
processed/stage17_architecture_policy_adapter_sft_1k.jsonl
processed/stage17_architecture_policy_toolmaze_perturbations_1k.jsonl
processed/stage17_architecture_policy_adapter_sft_toolmaze_1k.jsonl
STAGE16_RESULTS_TABLE_CN.md
STAGE17_PRIOR_ABLATION_CN.md
STAGE17_TOOLMAZE_HARD_NEGATIVE_CN.md
```

最新证据：

```text
runtime shadow matrix:
  eval_runs/20260701T_stage16_runtime_shadow_matrix_1k
  raw exact = 89.00%
  wrapped exact = 100.00%
  classifier exact = 100.00%
  classifier_no_next_prior exact = 30.40%

enum classifier with Strategist/Architect layers:
  clean 1k: eval_runs/20260701T_stage16_enum_classifier_clean1k_layers
  exact = 100.00%, strategist = 100.00%, architect = 100.00%
  mean = 0.00006163s

ToolBench-X style hard-negative:
  eval_runs/20260701T_stage16_enum_classifier_toolhazard_3912_layers
  rows = 3912
  exact = 100.00%, strategist = 100.00%, architect = 100.00%
  mean = 0.00006568s

ToolBench-X + APB unsolvable hard-negative:
  eval_runs/20260701T_stage16_enum_classifier_unsolvable_toolhazard_4912_layers
  rows = 4912
  exact = 100.00%, strategist = 100.00%, architect = 100.00%
  mean = 0.00006844s

rule distillation:
  processed/stage16_architecture_rule_distill_classifier_1k.jsonl
  rows = 110
  target eval = 100.00%

Stage17 adapter mix:
  processed/stage17_architecture_policy_adapter_sft_1k.jsonl
  rows = 1000
  source_mix = 110 rule-distillation + 890 hard-negative
  target eval = 100.00%
  classifier exact = 100.00%
  mean = 0.00007283s

Stage17 prior/guard ablation:
  native clean rows = 1720
  clean exact: full 100.00%, no_next 30.93%, no_tool 0.00%, no_permission 70.00%, no_hazard 99.77%
  hard-negative rows = 4912
  hard exact: full 100.00%, no_next 57.49%, no_tool 0.00%, no_permission 76.14%, no_hazard 68.57%

Stage17 ToolMaze implicit semantic failure:
  processed/stage17_architecture_policy_toolmaze_perturbations_1k.jsonl
  rows = 5216
  implicit_semantic_tool_failure = 304
  classifier exact = 100.00%
  no_hazard exact = 64.57%
  recommended adapter input = processed/stage17_architecture_policy_adapter_sft_toolmaze_1k.jsonl
  adapter rows = 1000, target/classifier eval = 100.00%
```

因此，后续不要再把 “remove wrapper rules” 当成目标本身；当前证据显示 no-next-prior exact 只有 30.40%。正确路线是先用 shadow matrix 记录依赖，再用 rule-distillation 数据逐步降低 raw model 错误。

## 0. 当前边界和结论先行

Stage16 不应该从“再训练一个更大 planner”开始。当前更有价值的方向是把已有路线变成可观测、可路由、可抗工具异常的 planner 系统：

1. 先做 runtime shadow：只旁路记录，不替换 `LocalAuditPlanner`。
2. 再做 step-level model routing/classifier：把 Stage10 的规则 route 升级为可训练的 per-step router，但必须保留 Stage10 suppressany 作为强基线。
3. 同步补 hard-negative/tool unreliability eval：从 clean heldout 走向 broken tool、extra tool、unsolvable task、conflict output。
4. 之后做 rule prior distillation：减少 Stage14 wrapper 对工具先验和 permission guard 的依赖，但不删除必要 guard。
5. 最后再做 Strategist/Architect 分层和 Medusa/Hydra/DSpark 加速：只有在 task-level 和 1k heldout 门槛过线后才考虑 runtime 接入。

当前本地最重要的基线：

| 路线 | 本地证据 | 结论 |
| --- | --- | --- |
| Stage7 单模型 | `eval_runs/20260627T-stage7compare-stage7-merged-heldout5001-1k/metrics.json`：1k schema 100.00%，command overlap 0.2294，mean 0.2062s | 单模型质量基线 |
| Stage10 suppressany route | `eval_runs/20260629T-stage10-online-route-longscriptonly-margin12-sec168-blockcomplete-suppressany-heldout5001-1k/metrics.json`：schema 100.00%，overlap 0.2302，mean 0.2178s，secondary 1.80%，changed 0.60% | 当前 fast-balanced route 基线 |
| Stage10 blockcomplete route | `eval_runs/20260629T-stage10-online-route-longscriptonly-margin12-sec168-blockcomplete-heldout5001-1k/metrics.json`：schema 100.00%，overlap 0.2303，mean 0.2199s，secondary 2.40%，changed 0.90% | quality-best，但成本更高 |
| Stage14 architecture-policy model | `eval_runs/20260701T_architecture_policy_model_stage14_r2_1k/`：raw schema 99.90%，四字段为 97.60%/93.10%/98.90%/98.00%；v4 deploy-only wrapper 后全部 100.00%，生成均摊 0.1491s | 可做 shadow 和 distillation，不可把 broad prompt dangerous guard 加回去 |
| Stage11 DSpark | `eval_runs/20260630T-stage11-dspark-128x200-seqverify-heldout5001-64/metrics.json`：schema 68.75%，overlap 0.1377，mean 2.5221s，target exact 78.12% | 证明训练步数有用，但还不是 serving 加速候选 |

## 1. 公开方法与本地映射

公开链接只作为方法对齐和指标设计参考，后续实验不要求安装新依赖，不要求跑网络命令。

| 方法/基准 | 公开链接 | 可借鉴点 | OpenClaw 落点 |
| --- | --- | --- | --- |
| RouterBench | [arXiv 2403.12031](https://arxiv.org/abs/2403.12031)，[GitHub](https://github.com/withmartian/routerbench) | 多模型 routing 的质量/成本权衡，适合做 query-level 基线 | 作为 Stage16 router 的最小 baselines：always Stage7、always Stage9、rule route、classifier route |
| TwinRouterBench | [arXiv 2605.18859](https://arxiv.org/abs/2605.18859)，[GitHub](https://github.com/CommonstackAI/TwinRouterBench) | step-level router-visible prefix、静态离线标签 + 动态 end-to-end 验证 | 把 OpenClaw 每个 subtask/LLM call 做成 step router row，先 offline RowExact/CostSave，再 task-level shadow |
| Agent Planning Benchmark | [arXiv 2606.04874](https://arxiv.org/abs/2606.04874) | feedback-conditioned step-wise planning、额外工具、坏工具、不可解任务 | 扩充 no-hint/native architecture heldout，专门测 planning vs execution 错因 |
| PlanBench-XL | [arXiv 2606.22388](https://arxiv.org/abs/2606.22388) | 大工具生态、工具检索受限、blocking mechanism | 为 OpenClaw 构造 extra tools / missing tools / blocked path 的本地 eval suite |
| ToolBench-X | [arXiv 2606.25819](https://arxiv.org/abs/2606.25819)，[GitHub](https://github.com/Foreverskyou/ToolBench-X) | Specification Drift、Invocation Error、Execution Failure、Output Drift、Cross-source Conflict | Stage16C 的 tool unreliability 注入类型直接按这五类设计 |
| Agent Lightning | [arXiv 2508.03680](https://arxiv.org/abs/2508.03680) | agent 执行和 RL 训练解耦、transition/credit assignment | 复用 `scripts/build_agent_lightning_transitions.py`，先做 transition reward 质量，不急着在线 RL |
| DeepAgent / ToolPO | [arXiv 2510.21618](https://arxiv.org/abs/2510.21618)，[GitHub](https://github.com/RUC-NLPIR/DeepAgent) | memory folding、tool-call advantage attribution、开放工具集 | 给 Strategist/Architect 分层和 tool token credit 提供参考 |
| ToolBench / ToolLLM | [arXiv 2307.16789](https://arxiv.org/abs/2307.16789) | Tool-use 数据构建、ToolEval、决策树式搜索 | 已是 Agent_Planner 数据路线背景，继续用于 hard-negative 和 tool-call reward |
| Medusa | [arXiv 2401.10774](https://arxiv.org/abs/2401.10774) | 多 decoding heads、tree attention、无独立 draft model 的加速路线 | 如果 DSpark cache 成本过高，可评估 Stage7 frozen backbone + planner head |
| Hydra | [arXiv 2402.05109](https://arxiv.org/abs/2402.05109)，[GitHub](https://github.com/zankner/Hydra) | sequentially-dependent draft heads，提高多头 draft token 准确率 | 比 Medusa 更适合 command JSON 的连续 token 预测，但必须先过 sequential exact |
| DeepSpec / DSpark | 本地快照：`external/DeepSpec` | target hidden-state cache、Qwen2 DSpark port、planner speculative evaluator | 继续 Stage11，但不直接跑官方默认大 cache；只做 planner-specific 小 cache 和 sequential diagnostic |

## 2. Stage16 总实验合同

所有 Stage16 子路线都必须满足：

```text
1. 不替换 backend/openclaw/planner.py。
2. 不改 AGENTS.md / STATUS.md，除非用户单独要求。
3. 新脚本、数据、报告使用 stage16 前缀，避免和其他 agent 的 Stage10/11/14 文件混在一起。
4. 64/128 样本只能算 smoke，晋级至少需要 1k heldout。
5. 触碰 runtime 行为前，必须先做 shadow，再做 task-level benchmark。
6. 粗暴降低风险但损失 command overlap 的方案不晋级。
```

推荐新增产物命名：

```text
processed/stage16_*.jsonl
processed/stage16_*.summary.json
configs/stage16_*.json
eval_runs/202607xxT-stage16-*/
models/stage16_*/
STAGE16_RESEARCH_ROADMAP_CN.md
```

统一指标：

```text
schema_valid_rate
command_overlap_mean
mean_amortized_request_seconds
tokens_per_second
long_command_rate
script_like_command_rate
validation_only_command_rate
complete_with_commands_rate
incomplete_without_commands_rate
retry_count
extra_candidate_rate
changed_from_primary_rate
shadow_exact_match_rate
task_success_rate
tool_unreliability_recovery_rate
calibrated_refusal_rate
unsafe_continue_rate
wrapper_correction_rate
```

硬拒绝条件：

```text
schema_valid_rate < 100.00% on 1k planner heldout
command_overlap_mean < 0.2294 without a compensating task-level gain
mean latency slower than Stage10 suppressany by >8% without quality gain
extra candidate / secondary branch rate rises above 5% without clear overlap gain
any unsafe auto-allow / destructive command regression
tool-unreliability clean-set success drop >1 percentage point
unsolvable task refusal failure >0 in safety-critical cases
```

## 3. Stage16A：Runtime Shadow Matrix

### 目标

把 Stage14 的 architecture-policy wrapper 从单点 1k eval 扩展为 runtime shadow matrix：在真实 LocalAuditPlanner 事件上记录“模型预测、rule prior、wrapper 修正、最终 runtime 决策”的差异，但不改变 runtime 输出。

### 为什么先做

Stage14 已经证明：

```text
raw model: schema 99.90%, model/next/context/executor = 97.60%/93.10%/98.90%/98.00%
v4 deploy-only wrapper: schema/model/next/context/executor = 100.00%
shadow_full_r1 with next_action priors: exact = 100.00%
shadow without next_action priors: exact = 30.93%
```

这说明 next_action guard 是必要组件。Stage16A 的问题不是“去掉规则”，而是量化哪些规则可以被模型学走，哪些必须留下。

### 需要新增或复用的文件

优先复用：

```text
scripts/architecture_policy.py
scripts/benchmark_architecture_policy_shadow.py
scripts/benchmark_architecture_policy_model.py
scripts/apply_architecture_policy_wrapper.py
```

建议新增：

```text
scripts/benchmark_runtime_shadow_matrix.py
configs/stage16_runtime_shadow_matrix.json
eval_runs/202607xxT-stage16-runtime-shadow-r1/
```

### 实验设计

输入：

```text
eval_runs/20260701T_architecture_full_r2/
eval_runs/20260701T_architecture_policy_shadow_full_r2/
eval_runs/20260701T_architecture_policy_model_stage14_r2_1k/
```

每条 row 输出字段：

```json
{
  "run_id": "...",
  "subtask_id": "...",
  "tool_name": "...",
  "permission_mode": "...",
  "runtime_expected": {},
  "raw_model_policy": {},
  "wrapped_policy": {},
  "rule_corrections": [],
  "would_change_runtime": false,
  "counterfactual_disable_next_prior": {},
  "counterfactual_disable_tool_prior": {},
  "risk_labels": []
}
```

核心指标：

```text
shadow_exact_match_rate
raw_to_wrapped_delta_by_field
wrapper_correction_rate_by_rule
would_change_runtime_rate
permission_mode_breakdown
tool_name_breakdown
next_action_prior_dependency_rate
```

建议命令，后续执行时再跑：

```bash
CUDA_VISIBLE_DEVICES=1 /home/litangchao/miniconda3/envs/AgentOpti/bin/python \
  data/litangchao/OpentClawOpti/Agent_Planner/scripts/benchmark_architecture_policy_shadow.py \
  --input-root data/litangchao/OpentClawOpti/Agent_Planner/eval_runs/20260701T_architecture_full_r2 \
  --output-dir data/litangchao/OpentClawOpti/Agent_Planner/eval_runs/202607xxT-stage16-runtime-shadow-r1
```

### 晋级条件

```text
shadow exact = 100.00% on all available native architecture event rows
wrapper correction rate <= current v4 deploy-only level, or correction reasons become more targeted
no permission mode regression
no next_action broad prompt dangerous guard regression
```

### 拒绝条件

```text
shadow exact < 99.50% on native rows
disable-next-action-prior still collapses exactness and the proposal removes that prior
wrapper uses full prompt text as mutating action for all variable execution tools
rule corrections increase but raw model accuracy does not improve
```

## 4. Stage16B：Step-Level Model Routing / Classifier

### 目标

把 Stage10 的手写 structural-risk route 升级为 step-level classifier。它不是全局问“用哪个模型”，而是在每个 planner step 上根据当前 prefix、risk labels、tool state、permission mode 和历史结果判断：

```text
Stage7 only
Stage7 + retry
Stage7 -> Stage9 secondary
Stage7 -> deterministic LocalAuditPlanner fallback
architecture-policy wrapper only
defer / await human
```

### 方法对应

RouterBench 给 query-level routing 的成本/质量框架；TwinRouterBench 更贴近 OpenClaw，因为它使用 router-visible prefix，并要求离线静态验证和 end-to-end 动态验证分开报告。

### 数据构造

建议新增：

```text
scripts/build_stage16_step_router_labels.py
scripts/train_stage16_step_router_classifier.py
scripts/benchmark_stage16_step_router.py
processed/stage16_step_router_labels_r1.jsonl
configs/stage16_step_router_r1.json
```

初始标签来源：

```text
Stage7 primary output
Stage9 secondary output
Stage10 suppressany selected output
Stage10 blockcomplete selected output
LocalAuditPlanner/audit_astar task-level outcome
Stage14 architecture-policy expected fields
failure taxonomy labels from planner_quality/gate_signal
```

每条 label row：

```json
{
  "row_id": "...",
  "prefix_features": {
    "prompt_tokens": 0,
    "tool_name": "...",
    "permission_mode": "...",
    "has_recent_failure": false,
    "has_output_files": false,
    "risk_labels": []
  },
  "candidate_metrics": {
    "stage7": {},
    "stage9": {},
    "route_suppressany": {},
    "deterministic_fallback": {}
  },
  "target_route": "stage7",
  "target_reason": "cheapest_equal_quality"
}
```

### 模型选择

第一版不要上大模型。先做可解释轻量 classifier：

```text
logistic regression / Naive Bayes / small sklearn-free linear scorer
输入：risk labels + prompt length bucket + tool/permission one-hot + Stage7 confidence proxy
输出：route class + calibrated confidence
```

如果不安装依赖，可用标准库实现：

```text
Counter-based Naive Bayes
per-feature log odds
heldout calibration table
```

### 核心指标

```text
RowExact: classifier route 是否等于 target_route
RouteSafePass: 被 classifier 改路的 row 是否保持 schema/overlap/risk 不差
CostSave: 相对 always Stage9 或 always quality route 节省的 secondary 成本
TaskPreserve: task-level benchmark 是否不掉分
ChangedRows: 相对 Stage10 suppressany 改了多少行
```

必须和这些基线对比：

```text
always Stage7
always Stage9
Stage10 threshold16 rejected route
Stage10 blockcomplete
Stage10 suppressany
oracle best-of-candidates
```

### 晋级条件

```text
1k schema = 100.00%
1k overlap >= 0.2302, or task-level benchmark shows statistically useful gain
mean latency <= Stage10 suppressany + 5%
extra-candidate rate <= 2.5% unless overlap gain >= 0.002
changed_from_primary_rate remains explainable and audited
```

### 拒绝条件

```text
classifier 只学到 prompt length，不能解释 route decision
offline RowExact 高但 online task-level 掉分
secondary branch rate >5% 且 overlap gain <0.002
validation_only / complete_with_commands 只被“绕过”而不是修复
```

## 5. Stage16C：Hard-Negative / Tool Unreliability Eval

### 目标

补齐 OpenClaw 当前最缺的评估层：工具环境不可靠时，planner 是否能识别、恢复或拒绝。现有 heldout 多数是 clean command/action JSON；Stage16C 要测 “工具变坏以后是否还会乱继续”。

### 方法对应

Agent Planning Benchmark 强调 extra tools、broken tools、unsolvable tasks 和 feedback-conditioned planning。PlanBench-XL 强调大工具生态下的 blocked path。ToolBench-X 把 tool unreliability 分成五类：

```text
Specification Drift
Invocation Error
Execution Failure
Output Drift
Cross-source Conflict
```

### 本地 suite 设计

建议新增：

```text
scripts/build_stage16_tool_unreliability_suite.py
scripts/benchmark_stage16_tool_unreliability.py
processed/stage16_tool_unreliability_suite_r1.jsonl
eval_runs/202607xxT-stage16-tool-unreliability-r1/
```

从现有 OpenClaw task/event 构造五种扰动：

| 扰动 | 本地实现 | 期望行为 |
| --- | --- | --- |
| Specification Drift | 工具说明中把参数名或输出字段轻微改名 | planner 重新检查 schema 或选择兼容字段 |
| Invocation Error | 第一次调用返回参数错误 | planner 修正参数，不重复原错误 |
| Execution Failure | 临时失败/timeout/permission denied | 有限 retry 或 fallback，不进入 loop |
| Output Drift | 工具返回格式合法但值偏移 | verifier 发现和上下文不一致 |
| Cross-source Conflict | 两个证据源冲突 | 请求更多证据或保守拒绝 |
| Extra Tools | 加入名字相似但错误的工具 | 不被噪声工具吸走 |
| Broken Tools | 唯一路径损坏但有替代路径 | 能找到替代路径 |
| Unsolvable | 所有路径都不满足 | calibrated refusal，不生成危险命令 |

### 指标

```text
clean_success_rate
hazard_recovery_success_rate
hazard_diagnosis_accuracy
retry_efficiency
fallback_success_rate
conflict_detection_rate
calibrated_refusal_rate
unsafe_continue_rate
loop_rate
invalid_tool_rate
```

### 晋级条件

```text
clean_success_drop <= 1 percentage point
recoverable hazard success beats Stage7/Stage10 baseline by >=5 percentage points
unsolvable calibrated_refusal_rate = 100.00% for destructive/safety cases
loop_rate = 0
unsafe_continue_rate = 0
```

### 拒绝条件

```text
靠更多 retry 提升 recovery，但 retry_efficiency 恶化且 latency 翻倍
无法区分 Execution Failure 和 Output Drift
对 Cross-source Conflict 给出自信错误 action
在 clean suite 上为了保守拒绝而明显降低 task success
```

## 6. Stage16D：蒸馏减少 Rule Prior

### 目标

把 Stage14 wrapper 中可学习的 rule corrections 蒸馏进模型，降低在线 wrapper 修正率；但保留 permission guard 和 next_action guard 中已经证明必要的部分。

### 当前问题

Stage14 v4 deploy-only wrapper 能把 1k 结果修到 100.00%，但这不代表模型自己学会了 architecture-policy。当前 raw 模型最弱字段是：

```text
next_action_accuracy: 93.10%
model_tier_accuracy: 97.60%
executor_kind_accuracy: 98.00%
context_policy_accuracy: 98.90%
```

Wrapper rule counts 显示仍有少量 correction：

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

### 数据路线

建议新增：

```text
scripts/build_stage16_rule_distill_data.py
processed/stage16_arch_rule_distill_r1.jsonl
models/stage16_arch_rule_distill_r1/
eval_runs/202607xxT-stage16-rule-distill-r1/
```

训练样本只取三类：

```text
1. raw wrong, wrapper right
2. raw parse failure, wrapper can normalize
3. counterfactual no-prior wrong, prior right
```

不要把所有 wrapper 输出无脑作为 SFT 数据，否则模型会学到“总是抄 rule prior”，而不是学会判断。

### Ablation

必须报告：

```text
raw model
raw + current v4 wrapper
distilled raw
distilled + minimal wrapper
distilled + no next_action prior
distilled + no tool prior
```

### 晋级条件

```text
distilled raw schema = 100.00% on 1k
next_action_accuracy >= 98.50% without broad prompt dangerous guard
minimal wrapper correction rate <= 50% of current v4
v4 wrapper 后仍保持四字段 100.00%
```

### 拒绝条件

```text
恢复 broad prompt dangerous guard
next_action_accuracy 低于当前 v4 wrapped 结果
raw accuracy 提升但 wrapper correction rate 不降
在 DEFAULT/DONT_ASK/EXPLORE permission mode 上出错
```

## 7. Stage16E：Strategist / Architect 分层

### 目标

把现在混在一起的能力拆成两层：

```text
Architect: 决定 model_tier、context_policy、executor_kind、verifier_next_action、风险/权限边界
Strategist: 在 Architect 给定边界下生成下一步 command/action JSON
```

这不是多 agent 炫技，而是为了降低 rule prior 和 command planner 的互相污染：Architect 管“该不该做、用什么工具、要不要等人”；Strategist 管“如果要做，下一步具体做什么”。

### 方法对应

DeepAgent/ToolPO 的启发是 memory folding、tool discovery 和 tool-call credit。Agent Lightning 的启发是把执行轨迹拆成 transition，给每步 credit，而不是只用最终成功/失败。

### 本地架构

第一版只做 offline shadow：

```text
input state/events
  -> Architect policy JSON
  -> deterministic guard/wrapper
  -> Strategist prompt augmentation
  -> Stage7 command/action JSON
  -> verifier / task-level shadow
```

建议新增：

```text
scripts/build_stage16_strategist_architect_data.py
scripts/benchmark_stage16_strategist_architect_shadow.py
processed/stage16_architect_train_r1.jsonl
processed/stage16_strategist_train_r1.jsonl
eval_runs/202607xxT-stage16-strategist-architect-shadow-r1/
```

### 数据来源

```text
architecture_full_r2 event files
openclaw_architecture_stage14_r2_compact_eval.jsonl
qwen_terminal_toolbench_sft_jsononly_strict_shortcmd120_action2_100k.jsonl
Agent Lightning transition rows from build_agent_lightning_transitions.py
Stage10 changed rows and failure taxonomy rows
```

### 指标

```text
architect_schema_valid_rate
architect_field_accuracy
strategist_schema_valid_rate
strategist_command_overlap_mean
architect_strategist_consistency_rate
wrong_tool_prevention_rate
unnecessary_command_rate
task_success_rate
```

### 晋级条件

```text
Architect wrapped fields = 100.00% on 1k native architecture eval
Strategist overlap >= Stage7 0.2294 under the same heldout
combined latency <= Stage10 suppressany + 10%
task-level benchmark does not regress
```

### 拒绝条件

```text
Architect 正确但 Strategist command overlap 掉到 Stage7 以下
分层后 latency 增加 >10% 且没有 hard-negative recovery gain
Architect 频繁把可执行任务变成 await_human
Strategist 绕过 Architect 的 permission/context 约束
```

## 8. Stage16F：Medusa / Hydra / DSpark 加速路线

### 目标

只在质量路线稳定后再做加速。当前 DSpark 已证明“训练步数不足”是瓶颈，但还没有证明可以替换 Stage7 serving。

### 当前 DSpark 状态

```text
best draft: models/openclaw_agent_planner/stage11_dspark_qwen2_planner_128x200/step_200
64 heldout sequential:
  schema_valid_rate = 68.75%
  command_overlap_mean = 0.1377
  mean_amortized_request_seconds = 2.5221s
  verify_rate = 0.2313
  accept_rates_by_position = [44.34%, 15.42%, 8.90%, 6.47%, 4.66%, 3.27%, 2.36%]
  target_greedy_exact_match_rate = 78.12%
```

这条线还不能晋级。下一步如果继续，必须先按 AGENTS 约束清理旧 draft/cache，再建 1k `[12,24]` cache，不能重复 20-step smoke。

### 三条加速候选

| 路线 | 优点 | 风险 | 何时做 |
| --- | --- | --- | --- |
| DSpark | 已有 Qwen2 port、cache builder、sequential evaluator | cache 成本、target exact、schema 仍低 | 先做 1k cache + 2-layer 200 step 起点 |
| Medusa | 不需要独立 draft model，适合 frozen Stage7 加 heads | 需要改模型 head 和 tree attention，工程风险高 | DSpark 1k 仍失败但想保留同模型加速时 |
| Hydra | sequential-dependent draft heads，理论上更适合连续 JSON token | 训练/集成比 Medusa 更复杂 | Medusa head acceptance 不够时再试 |

### DSpark 晋级实验

建议输出：

```text
eval_runs/202607xxT-stage16-dspark-cache-train1k-l384-layer12-24/
models/openclaw_agent_planner/stage16_dspark_qwen2_planner_1k_d2_step200/
eval_runs/202607xxT-stage16-dspark-1k-d2-seqverify-heldout5001-64/
eval_runs/202607xxT-stage16-dspark-1k-d2-seqverify-heldout5001-1k/
```

先 sequential diagnostic，再考虑 block verify speed probe：

```text
target_greedy_exact_match_rate
schema_valid_rate
command_overlap_mean
verify_rate
accept_rates_by_position
mean_target_greedy_seconds
mean_amortized_request_seconds
```

### 晋级条件

```text
1k sequential target_greedy_exact_match_rate >= 99.50%
1k schema_valid_rate = 100.00%
1k command_overlap_mean >= 0.2294
真实 latency 比 Stage7 至少低 8%-15%
block verify 与 sequential/HF generate 等价后才能报告 speed win
```

### 拒绝条件

```text
只在 64 样本上好看
target exact 仍低于 99.50%
schema 或 overlap 低于 Stage7
acceptance 提高但总延迟仍慢于 Stage7
需要超过本地 cache/磁盘预算才能继续
```

## 9. 推荐执行顺序

### 第一批：低冲突、高信息量

1. `Stage16A runtime shadow matrix`
   - 不改 runtime。
   - 只读已有 `architecture_full_r2` 和 Stage14 输出。
   - 产出 rule dependency 和 correction heatmap。

2. `Stage16B step-router label builder`
   - 不训练大模型。
   - 先把 Stage10/Stage14/Stage7/Stage9 的候选决策整理成监督数据。
   - 产出 classifier 是否值得做的 oracle upper bound。

3. `Stage16C tool unreliability suite`
   - 不需要新依赖。
   - 用本地事件和 synthetic perturbation 构造 hard-negative eval。
   - 先评估 baseline，不急着优化。

### 第二批：有训练但风险可控

4. `Stage16D rule-prior distill`
   - 只训练 correction rows。
   - 目标是降低 wrapper correction rate，不删除必要 guard。

5. `Stage16E Strategist/Architect shadow`
   - 先 shadow，再 task-level。
   - 只有 combined 指标优于单 Stage7/Stage10 才考虑接近 runtime。

### 第三批：成本高、必须有清理前置

6. `Stage16F DSpark/Medusa/Hydra`
   - 先清理旧大 cache/旧 draft。
   - DSpark 先 1k cache + sequential diagnostic。
   - Medusa/Hydra 只作为 DSpark 不经济时的 head-based 替代路线。

## 10. Stage16 报告模板

每次实验必须落一个 `report.md` 或 summary JSON，至少包含：

```text
stage16_subroute:
run_id:
input_paths:
model_paths:
config_paths:
sample_count:
baseline:
changed_files:
metrics:
  schema_valid_rate:
  command_overlap_mean:
  mean_amortized_request_seconds:
  extra_candidate_rate:
  changed_from_primary_rate:
  shadow_exact_match_rate:
  hard_negative_recovery_rate:
  unsafe_continue_rate:
decision:
  promote / keep_shadow / reject
rejection_reason:
next_action:
```

## 11. 最小可执行下一步

如果下一位 agent 接着做，建议不要马上训练，先做这两个文件：

```text
scripts/build_stage16_step_router_labels.py
scripts/build_stage16_tool_unreliability_suite.py
```

然后各跑一个小 smoke：

```text
eval_runs/202607xxT-stage16-step-router-labels-smoke/
eval_runs/202607xxT-stage16-tool-unreliability-smoke/
```

成功标准不是指标多漂亮，而是数据 schema 稳定、来源可追溯、能和 Stage7/Stage10/Stage14 的真实 metrics 对齐。
