# 我在 OpenClawPOpti 中完成的工作总结

更新日期：2026-06-19

## 总体概述

我在这个项目中主要负责 OpenClaw Agent Optimization Capstone 的 Planner 方向，把最初的规划型 agent 优化想法推进成了一个可以运行、可以审计、可以复现实验的原型系统。

当前项目的核心目标是：在 AgentScope 2 / ReAct 风格 agent 的基础上，加入一个显式的 planner search layer，用搜索式规划替代简单贪心选择，从而提升多步工具任务中的成功率、权限处理质量、审计完整性和安全性。

一句话总结就是：我实现了一个审计优先的 AgentScope 2 Planner 优化原型，并用本地 benchmark 证明 `audit_astar` 相比 `greedy_topk` baseline 有明显效果提升。

## 我确定的项目方向

Capstone 原本包含三个优化方向：

- Strategist：根据任务难度选择更合适、更低成本的模型。
- Architect：按需注入上下文，而不是一次性把全部上下文塞进 prompt。
- Planner：用搜索式规划替代一步一步的贪心执行。

我把当前代码库的重点放在 Planner 方向。这个方向最适合当前项目，因为它可以直接利用已有的 agent runtime、工具调用、权限门控和审计日志，并且可以通过本地 benchmark 产出可量化证据。

因此，我的研究问题被明确为：

> 显式搜索规划层能否在保持审计性和安全边界的前提下，提升 AgentScope 风格工具 agent 的任务执行表现？

## 我实现的系统能力

### 1. 审计优先的后端系统

我实现了后端核心模块，位置在 `backend/openclaw/`：

- `server.py`：提供 REST API 和 SSE 事件流，用于创建 run、查询 run、读取事件和审计报告。
- `planner.py`：实现 `LocalAuditPlanner`，负责任务归一化、候选动作生成、路径选择、权限检查、工具执行模拟和最终回答。
- `permissions.py`：实现权限引擎，把每个 action 判断为 `allow`、`ask` 或 `deny`。
- `storage.py`：负责把 run 状态、事件和审计报告落盘。
- `audit.py`：把一次 run 的事件序列渲染成 Markdown 审计报告。
- `models.py`：定义 run、event、candidate step 和 permission decision 等结构化数据模型。

这部分让项目从一个概念变成了一个可运行的后端系统。每次任务执行都会生成结构化事件、状态文件和可读的审计报告。

### 2. AgentScope 2 集成

我把 AgentScope 2 作为真实 agent runtime 集成到项目里，同时保持 OpenClaw 自己掌握权限控制和审计落盘：

- `as2_adapter.py`：负责 AgentScope 包检测、provider 配置、事件映射和权限模式映射。
- `as2_runtime.py`：构建真实 AS2 `Agent`、`Toolkit`、`AgentState`、`PermissionContext` 和 `ReActConfig`。
- `as2_openai.py`：支持 OpenAI-compatible provider 调用。

这个设计的关键点是：AS2 可以负责生成候选动作，但最终的权限门控、审计记录和状态持久化仍由 OpenClaw 控制。这样既能利用 framework 能力，也不会丢掉安全性和可解释性。

没有模型 API key 时，系统会自动退回 deterministic planner，因此 demo、测试和 benchmark 不依赖真实模型也能完整运行。

### 3. 前端演示界面

我实现了一个静态前端，位置在 `frontend/`：

- `index.html`
- `styles.css`
- `app.js`

前端支持配置 API 地址、选择权限模式、创建 planner run、查看历史 run、通过 SSE 实时显示事件 timeline，并读取 `audit.md` 审计报告。

这让项目可以直接演示完整工作流，而不是只能通过命令行展示后端结果。

### 4. Baseline planner 和优化 planner

我实现并比较了两种 planner strategy：

- `greedy_topk`：baseline。它对候选动作独立打分，然后选择排名最高的若干步执行。
- `audit_astar`：优化版。它使用 bounded A* 风格搜索，在候选 tool/action path 上综合风险、权限摩擦、重复动作、证据覆盖和目标完成度来选择更优路径。

`audit_astar` 的实现位于 `backend/openclaw/search_planner.py`。它不仅选择路径，还会记录 `search_started`、`search_expand`、`search_score`、`search_prune` 和 `search_selected` 等搜索事件，使 planner 的优化过程本身也能被审计。

### 5. Benchmark 体系

我搭建了本地 planner benchmark harness：

- `backend/openclaw/benchmark.py`
- `benchmarks/tasks/*.json`
- `data/benchmarks/{timestamp}/metrics.json`
- `data/benchmarks/{timestamp}/report.md`

benchmark 任务覆盖 workspace grounding、permission trap、tool path、safety、production safety 和 ambiguity 等类型。当前 suite 包含 24 个任务，并划分为 15 个 dev task 和 9 个 holdout task，避免只在调参任务上证明效果。

benchmark 支持：

- 对比不同 planner strategy。
- 运行 deterministic runtime 或 AS2/model-backed runtime。
- 按 `dev`、`holdout` 或 `all` split 运行。
- 输出 Markdown 报告和 JSON 指标。
- 检查 stop criteria 是否满足。

### 6. 可复现实验结果

最新 benchmark 结果位于：

- `data/benchmarks/20260618T091019Z/report.md`
- `data/benchmarks/20260618T091019Z/metrics.json`

该实验使用 deterministic runtime，包含 24 个任务，每个 strategy 重复 3 次，并满足 stop criteria。

总体结果：

| Strategy | Success rate | Mean score | Mean latency | Invalid tools | Hallucinated actions | Loop failures | Unsafe auto-allow |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `audit_astar` | 100.00% | 1.0000 | 0.3255s | 0 | 0 | 0 | 0 |
| `greedy_topk` | 20.83% | 0.7361 | 0.2833s | 0 | 0 | 0 | 0 |

holdout split 结果：

| Strategy | Success rate | Mean score | Mean latency |
| --- | ---: | ---: | ---: |
| `audit_astar` | 100.00% | 1.0000 | 0.3470s |
| `greedy_topk` | 33.33% | 0.7963 | 0.2823s |

这说明在当前本地 benchmark 协议下，`audit_astar` 在整体任务和 holdout 任务上都明显优于 `greedy_topk`，同时没有引入 invalid tool、hallucinated action、loop failure 或 unsafe auto-allow 回归。

## 我补充的测试和文档

测试位于 `tests/`，覆盖 planner、permission gate、AS2 adapter/runtime、search planner、benchmark runner 和 server endpoint。它们用于保证核心行为不会在后续修改中被破坏。

文档位于 `docs/`：

- `MVP_PLAN.md`：定义 MVP 范围、系统架构和验收标准。
- `AS2_ARCHITECTURE.md`：说明 AgentScope 2 runtime 如何接入 OpenClaw。
- `CAPSTONE_PLANNER_RESEARCH.md`：整理 Planner 方向的研究依据、方法选择和实验思路。
- `PLANNER_BENCHMARKS.md`：说明 benchmark 设计、指标、stop criteria 和当前结果。
- `PROJECT_SUMMARY.md`：总结项目当前状态、能力和限制。

## 当前项目可以展示的成果

目前这个项目可以展示四类成果：

1. 可运行系统：可以启动后端和前端，创建 planner run，并实时查看事件。
2. 可审计执行：每次 run 都会产生 `state.json`、`events.jsonl` 和 `audit.md`。
3. 可解释优化：`audit_astar` 的搜索过程会被记录成事件，而不是只有最终结果。
4. 可量化证据：benchmark 有任务集、dev/holdout split、重复运行、metrics 和 report。

## 当前边界

当前项目还不是完整的三方向 Capstone 最终版本：

- Strategist/model routing 还没有实现，只是 provider 配置已经集中，后续可以接入 RouteLLM 或 FrugalGPT 风格路由。
- Architect/progressive context 还没有完整实现 memory、retrieval、compaction 或 just-in-time context injection。
- `audit_astar` 是 bounded A* 风格 planner，还不是完整 LATS/MCTS。
- 当前最强实验结果来自 deterministic runtime，model-backed AS2 runtime 还需要在稳定 provider 配置下继续重复实验。

## 下一步计划

如果继续推进，我建议按以下顺序做：

1. 在真实 AS2/model-backed runtime 下重复运行 dev/holdout benchmark。
2. 把 `greedy_topk` vs `audit_astar` 的对比整理成 Capstone 实验章节。
3. 增加 `audit_lats` 或 MCTS-lite planner，作为 Planner 方向的 stretch contribution。
4. 扩展 benchmark 任务集，加入更接近真实 OpenClaw repo 工作流的多步任务。
5. 如果需要覆盖完整三方向，再补 Strategist 的模型路由和 Architect 的渐进式上下文注入。

## 可复现实验命令

运行测试：

```bash
.venv/bin/python -m unittest discover -s tests
```

运行默认 benchmark：

```bash
.venv/bin/python backend/openclaw/benchmark.py --repeats 3
```

只运行 holdout：

```bash
.venv/bin/python backend/openclaw/benchmark.py --split holdout --repeats 3
```

启动后端：

```bash
scripts/start_backend.sh
```

启动前端：

```bash
scripts/start_frontend.sh
```

启用 A* planner：

```bash
OPENCLAW_PLANNER_STRATEGY=audit_astar scripts/start_backend.sh
```
