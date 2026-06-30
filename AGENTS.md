# Agents Working Agreement

本文件记录本仓库中用户和 Codex 已经明确下来的协作要求，后续 agent 在 `/home/litangchao/OpenClawPOpti` 工作时优先遵守。

## 对话与执行方式

- 默认用中文说明结果、进度和取舍；除非用户明确要求英文。
- 用户说“继续”时，延续上一轮的具体实现或验证，不重新从概念讨论开始。
- 用户更偏向实际执行、训练、评估和落盘文档；不要只给路线建议。
- 每次优化都要有可复现产物和指标，记录正结果与负结果，避免重复试错。
- 不确定方向时可以并行比较路线，但必须用同一 heldout/benchmark 口径判断。

## 环境与资源

- OpenClaw 相关命令默认使用 `/home/litangchao/miniconda3/envs/AgentOpti/bin/python`。
- GPU 实验默认使用 GPU1，并显式设置 `CUDA_VISIBLE_DEVICES=1`。
- 训练、合并、评估都应在 `AgentOpti` 环境中执行，除非某个 serving 栈已经明确需要单独环境。
- 重要评估命令优先写入 `data/litangchao/OpentClawOpti/Agent_Planner/eval_runs/`，模型写入 `data/litangchao/OpentClawOpti/Agent_Planner/models/`，处理数据写入 `data/litangchao/OpentClawOpti/Agent_Planner/processed/`。

## Agent_Planner 边界

- `Agent_Planner` 是独立 planner-model 训练路线，不要默认替换 `backend/openclaw/planner.py` 的 deterministic/runtime planner。
- 只有当用户明确要求接入 runtime，或者 task-level benchmark 证明稳定后，才考虑把模型 planner 接进主流程。
- OpenClaw 当前 task-level 路线仍以 profile-aware `LocalAuditPlanner` 为主；模型 planner 主要用于 command/action JSON 的离线训练和 serving profile 评估。
- 数据路线坚持“无人工标注优先”：复用 ToolBench/Qwen Terminal ToolBench/OpenClaw rollout/Agent Lightning transition 等自动轨迹和 reward/filter。

## 当前模型与路线决策

- 当前最佳单模型候选是 `models/20260627T-stage7-verifier-combined3k-500-merged`。
- Stage7 1k heldout 基准：schema 100.00%，command overlap 0.2294，平均摊销约 0.2048s。
- Stage9 PRM-DPO 比 Stage8 DPO 稳，但不能替换 Stage7；它可作为结构风险样本的第二候选。
- 原 Stage7 + Stage9 structural-risk threshold16 路由已降级：真实在线 1k 为 schema 100.00%，overlap 0.2287，mean 0.2429s；风险下降但 overlap 回退、延迟约 +12%。
- 当前实验 serving Pareto：`configs/stage10_structrisk_route_longscriptonly_margin12_sec168_blockcomplete_suppressany.json` 是 fast-balanced 推荐，真实在线 1k schema 100.00%，overlap 0.2302，触发 Stage9 1.80%，切换 0.60%，相对同轮 Stage7 延迟约 +5.7%。`configs/stage10_structrisk_route_longscriptonly_margin12_sec168_blockcomplete.json` 是 quality-best，overlap 0.2303，但触发 2.40%、延迟约 +6.6%。`configs/stage10_structrisk_route_longscriptonly_margin12_sec168_blockcomplete_suppresscomplete.json` 是 speed/safety 变体，overlap 0.2301、long 0.90%、script 1.60%、延迟约 +5.5%。
- DeepSpec/DSpark 已进入 Stage11 深度融合路线，但不要直接跑官方默认管线：官方 Qwen3-4B target-cache 路线约 38 TB 且默认 8 GPU。当前 1k offline acceptance probe 显示 Stage6-as-draft 前缀匹配仅 8.13%、aligned token match 12.46%，已拒绝；Stage9-as-draft 前缀匹配 58.11%、aligned token match 64.81%，说明 Stage7 输出可预测，但 Stage9 同尺寸不能加速。已把官方 DeepSpec 快照放入 `data/litangchao/OpentClawOpti/Agent_Planner/external/DeepSpec`，并新增 Qwen2 DSpark port、planner direct target-cache builder、smoke config 和 planner 专用 speculative benchmark。GPU1 已跑通 8 样本 target cache、1-step trainer smoke（loss 4.3045）和 128 样本 cache（0.5312 GiB）+ 多轮短训。20260630 evaluator 已修：读取 Stage7 `repetition_penalty=1.05`，新增 eager diagnostic、显式 attention/cache、4D causal block mask、`--verify-mode sequential` 和 `--accept-margin`。128x20/d2 原始 draft 不晋级：16 条 sequential schema 75.00%、overlap 0.1106、mean 2.7097s、verify_rate 0.1320、acceptance `[5.62%,0,0,0,0,0,0]`。4-layer 128x20 也不晋级：acceptance 完全不变且 mean 变慢到 2.8588s。增加训练步数有效：128x100/d2 16 条 verify_rate 0.1698、acceptance `[31.25%,4.27%,0.34%,0,0,0,0]`；当前最佳 Stage11 draft 是 `models/openclaw_agent_planner/stage11_dspark_qwen2_planner_128x200/step_200`，64 条 sequential schema 68.75%、overlap 0.1377、mean 2.5221s、verify_rate 0.2313、acceptance `[44.34%,15.42%,8.90%,6.47%,4.66%,3.27%,2.36%]`、target exact 78.12%。它仍未晋级，因为 sequential 是 correctness diagnostic 而非最终 speed path，schema/overlap 也远低于 Stage7 1k 门槛；但它证明“训练步数不足”是真瓶颈，下一步应扩 1k cache 而不是继续 20-step smoke。
- 已否决路线：直接 Stage8 DPO 替换、Stage9 单模型替换、宽泛 threshold16 在线路由、progress-policy prompt、strict failure-repair SFT、final-check command postprocess。

## 评估门槛

- 64/128/512 样本只能作为探索；模型或 serving profile 晋级至少需要 1k heldout 证据。
- 默认对比指标：schema_valid_rate、command_overlap_mean、mean_amortized_request_seconds、long_command_rate、script_like_command_rate、validation_only_command_rate、retry_count。
- 单模型替换必须优于 Stage7 的 1k overlap 或在 overlap 基本不降的前提下显著降低风险/延迟。
- serving 路由若增加第二候选，必须报告 extra-candidate rate、changed rows、真实或估算 online latency 和风险变化；真实在线结果优先于离线重排估计。
- 粗暴降低风险但损失 command overlap 的方案不得晋级。

## 文件与 Git 保护

- 不要回滚用户或前序 agent 已有改动，尤其是 `README.md`、`backend/openclaw/*`、`tests/*` 中的历史变更。
- 编辑前先确认工作树状态；只改当前任务需要的文件。
- 手工代码修改使用 `apply_patch`。
- 训练/评估产物可能被 `.gitignore` 忽略；即使 `git status` 不显示，也要在最终结果中写清真实路径。
- 提交/推送前必须重新确认真实 git checkout 状态；历史上该目录曾出现 `.git` 损坏/占位问题。

## 推荐下一步

- 优先围绕 `configs/stage10_structrisk_route_longscriptonly_margin12_sec168_blockcomplete_suppressany.json`、`scripts/planner_route_policy.py` 和 `scripts/benchmark_transformers_route_planner.py` 继续完善在线 route wrapper，而不是继续盲目训练。
- 下一步优化方向：进一步降低 secondary 分支成本、提高 Stage9 在 long/script 风险样本上的相关性，或从 sec168_blockcomplete/suppressany 成功切换样本挖掘更干净的训练对；不要重复小样本 repair SFT。
- 若继续 DeepSpec/DSpark，先清理被否掉的大模型/旧 draft，当前 `Agent_Planner` 树约 94G，已超过原先 50G 约束；1k `[12,24]` cache 估算 4.1093GiB。清理后再建 `train1k-l384-layer12-24` cache，并以 2-layer 200 step 作为起点训练，不要再跑 20-step smoke 或 4-layer 128x20。评估仍先用 `--verify-mode sequential` 跑 64/1k diagnostic，确认 target-only exact、draft acceptance、schema/overlap 和真实 latency；block verify 只能在 Qwen2 block target forward 与 sequential/HF 生成等价后作为 speed probe。晋级门槛仍是 1k heldout schema 100.00%、overlap 不低于 0.2294、真实延迟至少比 Stage7 低 8%-15%。
- Agent Lightning/RLVR 方向应先保证 transition reward 分解质量，再进入在线 RL。
