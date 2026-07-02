# OpenClawPOpti 期中个人贡献报告

这份 README 是我针对小组期中报告准备的个人负责部分草稿。内容对应英文版 `README.md`，重点放在我负责的 OpenClaw agent optimization 项目中的 Planner 方向。写法偏报告风格，方便先在组内确认，再合并进最终英文版小组报告。

## 1. 产出目标

我的目标是为 AgentScope 风格的工具型 agent 构建并验证一个可审计的 planner layer。这个 planner 的核心作用，是在多步任务中选择比简单贪心 baseline 更安全、更符合目标的工具和动作路径。

这个方向的预期产出不只是一个概念设计，而是一个可以运行的原型系统。它需要包含 API endpoint、事件轨迹、权限决策、benchmark 任务、评估报告，以及足够的证据，支持我们在期中汇报中说明目前已经完成了什么。

我负责部分的核心研究问题是：

> 显式的 planner search layer 能否在保持每一步决策可审计的前提下，提升 agent 的工具选择、权限处理和任务成功率？

## 2. 技术架构和方案规划

当前 Planner 方向实现为一个围绕 AgentScope 2 思路设计的 audit-first runtime。系统保持前后端边界简单，同时把 model-backed AgentScope 执行能力隔离在 adapter 层之后。

```text
静态前端控制台
  -> OpenClaw REST/SSE API
  -> RunManager session
  -> LocalAuditPlanner control plane
  -> 可选 AgentScope 2 runtime boundary
  -> OpenClaw permission gate
  -> 持久化 events.jsonl, state.json, audit.md
```

主要后端模块如下：

| 模块 | 文件 | 作用 |
| --- | --- | --- |
| API 和 run 管理 | `backend/openclaw/server.py` | 提供健康检查、创建 run、查询 run、读取事件、事件流和 audit 报告接口。 |
| Planner 控制面 | `backend/openclaw/planner.py` | 生成候选步骤、选择 planner path、执行权限判断、模拟安全工具执行并生成最终输出。 |
| Search planner | `backend/openclaw/search_planner.py` | 实现 `greedy_topk`、`audit_astar` 和 `audit_reflexion`。 |
| 权限门控 | `backend/openclaw/permissions.py` | 根据当前 permission mode，把每个 action 映射为 `allow`、`ask` 或 `deny`。 |
| 审计持久化 | `backend/openclaw/storage.py`, `backend/openclaw/audit.py` | 保存 run state、事件日志和 Markdown audit 报告。 |
| AgentScope 集成 | `backend/openclaw/as2_adapter.py`, `backend/openclaw/as2_runtime.py`, `backend/openclaw/as2_openai.py` | 检测 AgentScope、构建可选 model-backed runtime，并在无凭证时回退到 deterministic candidates。 |
| Benchmark | `backend/openclaw/benchmark.py`, `backend/openclaw/model_matrix.py` | 评估不同 planner strategy 和 provider/model 配置。 |
| 学习型 planner hint | `backend/openclaw/planner_profile_model.py`, `scripts/train_planner_profile_model.py` | 训练轻量 Naive Bayes profile model，用于无显式 hint 时的 workflow/tool routing。 |

baseline strategy 是 `greedy_topk`，它会独立排序候选 action，并选择分数最高的步骤。优化策略包括：

- `audit_astar`：一个 bounded A* 风格 planner，会在候选 tool/action path 上进行搜索。它综合 impact、evidence value、reversibility、risk、permission friction、重复 action 和缺失目标工具等因素来评分。
- `audit_reflexion`：一个 reflective 版本。它从 A* path 出发，再进行确定性的 review/repair，并添加 `reflection_*` 事件，让修正过程也进入审计轨迹。

这个架构的关键点是：OpenClaw 始终负责权限判断和证据记录。即使启用了 model-backed AgentScope runtime，模型也只是提出候选步骤，最终的执行边界、权限门控和审计落盘仍由 OpenClaw 控制。

## 3. 目前的产出成果和进展

到期中节点为止，我负责的 Planner 部分已经完成以下产出：

- 一个可运行的后端 planner service，支持 REST 和 SSE 接口。
- 一个位于 `frontend/` 的静态前端控制台，可以创建 run、查看实时事件并读取 audit 报告。
- 一个本地 permission engine，可以把 action 分类为 `allow`、`ask` 或 `deny`。
- 三种 planner strategy：`greedy_topk`、`audit_astar` 和 `audit_reflexion`。
- AgentScope 2 集成边界，并在 provider credentials 未配置时提供 deterministic fallback。
- 一个带 dev / holdout split 的 benchmark harness。
- 从 PhoneHarness、tau2-bench-data、ToolBench 和 SkillsBench 转换并规范化得到的 planner task suites。
- 一个基于本地多源 fixture 训练的轻量 planner profile model。
- 已持久化的 benchmark report、JSON metrics 和每次 run 的 audit artifacts。

最新 deterministic benchmark 使用 88 个任务，其中 61 个 dev 任务、27 个 holdout 任务，每个 strategy 重复运行 3 次。它对比了 greedy baseline 和优化后的 planner strategies。

| Strategy | Success rate | Mean score | Mean latency | Search events | Reflection events | Invalid tools | Hallucinated actions | Loop failures | Unsafe auto-allow |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `audit_astar` | 100.00% | 1.0000 | 0.2778s | 38.5909 | 0.0000 | 0 | 0 | 0 | 0 |
| `audit_reflexion` | 100.00% | 1.0000 | 0.2902s | 32.0455 | 4.5000 | 0 | 0 | 0 | 0 |
| `greedy_topk` | 5.68% | 0.7528 | 0.2846s | 0.0000 | 0.0000 | 0 | 0 | 0 | 0 |

在 holdout split 上，两个优化策略都达到 100.00% success rate，而 `greedy_topk` 为 11.11%。这说明在当前本地 deterministic benchmark 设置下，显式规划明显改善了结果，并且没有引入 safety regression。

planner profile model 也提供了初步的 no-hint generalization 证据。它基于来自 PhoneHarness、tau2、ToolBench 和 SkillsBench 的 325 个本地样本训练。holdout 上的 planner profile 预测准确率为 100.00%，execution-tool 预测准确率为 95.06%，policy-mode 预测准确率为 64.20%。

## 4. 当前产出的证据

当前证据直接保存在仓库中：

| 证据类型 | 位置 |
| --- | --- |
| Planner runtime 代码 | `backend/openclaw/planner.py` |
| Planner search 算法 | `backend/openclaw/search_planner.py` |
| 权限门控 | `backend/openclaw/permissions.py` |
| AgentScope 2 adapter/runtime | `backend/openclaw/as2_adapter.py`, `backend/openclaw/as2_runtime.py` |
| Benchmark runner | `backend/openclaw/benchmark.py` |
| Benchmark task suites | `benchmarks/tasks/*.json` |
| 最新 benchmark report | `data/benchmarks/20260622T144217Z/report.md` |
| 最新 benchmark metrics | `data/benchmarks/20260622T144217Z/metrics.json` |
| 每次 run 的 audit 示例 | `data/benchmarks/20260622T144217Z/artifacts/**/audit.md` |
| Planner profile model | `data/planner_models/profile_policy_model.json` |
| Planner profile model report | `data/planner_models/profile_policy_report.md` |
| 架构说明 | `docs/AS2_ARCHITECTURE.md` |
| Benchmark 设计说明 | `docs/PLANNER_BENCHMARKS.md` |
| MVP 计划 | `docs/MVP_PLAN.md` |

可复现实验命令：

```bash
python -m unittest discover -s tests
python backend/openclaw/benchmark.py --repeats 3
python backend/openclaw/benchmark.py --split holdout --repeats 3
OPENCLAW_PLANNER_STRATEGY=audit_reflexion scripts/start_backend.sh
```

目前还没有把最终 UI 截图提交进仓库。小组报告提交前，可以补充前端控制台、事件 timeline 和生成的 `audit.md` 页面截图，作为更直观的可视化证据。

## 5. 当前产出的风险、挑战和局限性

第一个主要局限是：当前最强证据来自 deterministic local benchmark。AgentScope 2 model-backed 路径已经存在，但真实 provider 质量对比仍需要稳定 API key，并在相同 benchmark protocol 下重复评估。

第二个局限是：`audit_astar` 是 bounded A* 风格 search，不是完整的 LATS 或 MCTS planner。它更简单、更容易审计，但目前还没有完整 rollout simulation 或 backpropagation。

第三个风险是 benchmark 覆盖范围。当前 suite 覆盖 workspace grounding、permission trap、safety、deployment risk、mobile/CLI/MCP-style workflow、policy-tool-agent task、API planning task 和 skill workflow。但是最终评估还应该加入更多接近真实 OpenClaw 使用场景的 repo-grounded 多步任务。

第四个局限是项目范围。我负责的是 Planner 方向。整体 capstone 可能还会包含 Strategist 和 Architect 方向，但这些方向需要谨慎集成，避免最终系统变成多个互不连接的 demo。

## 6. 期末时的计划与目标

期末前，我计划从四个方面继续加强 Planner 贡献：

1. 使用真实 credentials 跑 model-backed AS2/provider benchmark，并和 deterministic fallback 进行对比。
2. 扩展 benchmark 任务，加入更真实的 OpenClaw workflow，尤其是 repo-grounded editing、validation 和 deployment-safety 场景。
3. 只有在相同 holdout protocol 下能达到或超过 `audit_astar` 时，才继续强化 reflective planner。
4. 补充最终报告证据，包括前端截图、benchmark 表格、生成的 audit reports 和简洁架构图。

我的期末目标是交付一个可被团队清楚展示的 planner optimization module：有 baseline vs optimized planner 对比，有清晰架构，有可复现 benchmark protocol，也有可审计的 run artifacts。

## 7. 自己在团队中的负责部分和 contribution

我在团队中负责 Planner 方向。我的 contribution 是把 planner idea 推进成一个可以运行、可以评估、可以展示证据的原型系统。

具体来说，我完成了：

- 设计 audit-first planner architecture。
- 实现 backend planner runtime 和 API flow。
- 实现 baseline 和 optimized planner strategies。
- 集成 AgentScope 2 runtime boundary。
- 构建 permission gate 和 audit logging path。
- 构建 benchmark tasks、evaluation metrics 和 report generation。
- 将外部 planner/workflow datasets 转换为本地 OpenClaw benchmark fixtures。
- 训练并评估轻量 planner profile model。
- 编写 architecture、benchmark design 和 project progress 相关技术文档。

## 8. AI 使用声明

我使用了 AI coding assistants，包括 ChatGPT/Codex，来辅助 implementation planning、code drafting、debugging、documentation，以及 benchmark evidence 的整理总结。AI 的作用是辅助生成和修改代码、组织报告语言，并检查文字说明是否和仓库 artifacts 对齐。

最终的技术方向由我选择，生成的代码和文档由我检查，benchmark evidence 由我运行或检查后用于报告。没有向 AI 工具提供 secret keys，API credentials 也应保留在本地环境变量中，而不是提交到仓库文件里。
