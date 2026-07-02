# OpenClawPOpti 项目工作总结

更新日期：2026-06-19

## 一句话总结

我把 OpenClawPOpti 从一个 Planner 方向的 Capstone 想法，推进成了一个可运行、可审计、可 benchmark 的 AgentScope 2 Planner 优化原型。当前项目的核心成果是：在真实 AgentScope 2 运行时外层实现审计优先的 planner 控制面，并用本地 benchmark 证明 `audit_astar` 相比 `greedy_topk` 在任务成功率和平均得分上有明显提升。

## 我选择并明确了项目方向

Capstone 原本有三个优化方向：

- Strategist：根据任务难度选择更便宜或更强的模型。
- Architect：按需注入上下文，而不是一次性塞满 prompt。
- Planner：用显式搜索替代贪心式的一步执行。

我最终把当前代码库的重点落在 Planner 方向：证明一个显式、可审计的搜索规划层，能改善 AS2/ReAct 风格 agent 的工具选择、权限决策和多步任务执行质量。这个定位已经整理在 `README.md` 和 `docs/CAPSTONE_PLANNER_RESEARCH.md` 里。

## 我完成的主要工作

### 1. 写出了 MVP 计划和研究路线

我先把实现方案写成 `docs/MVP_PLAN.md`，明确了 MVP 的边界：

- 后端使用 Python 标准库 HTTP 服务，避免依赖 Node/npm 或额外 app-server 基础设施。
- 前后端解耦，后端暴露 REST 和 SSE，前端只调用 API。
- 每次 run 都要生成可复盘证据：`state.json`、`events.jsonl`、`audit.md`。
- 权限门控是核心能力，每个候选动作都必须被分类为 `allow`、`ask` 或 `deny`。
- AS2 放在 runtime/adapter 边界后面，OpenClaw 本地仍然掌握权限、审计和落盘。

在 `docs/CAPSTONE_PLANNER_RESEARCH.md` 里，我进一步把项目和 ReAct、Reflexion、Tree of Thoughts、ToolChain*、LATS/MCTS、AgentBench、tau-bench 等方法联系起来，明确当前贡献不是“从零写一个 agent”，而是在 AgentScope 风格运行时上证明 planner search layer 的收益。

### 2. 实现了 AS2 审计型后端

后端核心模块位于 `backend/openclaw/`：

- `server.py`：提供 REST/SSE API，包括健康检查、创建 run、查询 run、读取事件、读取 audit 报告和流式事件。
- `planner.py`：实现 `LocalAuditPlanner`，负责候选生成、planner path 选择、权限检查、事件写入、工具模拟和最终回答。
- `permissions.py`：实现 `PermissionEngine`，把动作按权限模式映射成 `allow`、`ask`、`deny`。
- `storage.py`：负责 run 状态、事件和 audit 文件持久化。
- `audit.py`：把每次 run 的事件序列渲染为 Markdown 审计报告。
- `models.py`：定义 run、event、candidate step、permission decision 等结构化数据模型。

这让项目不只是一个 planner 想法，而是有真实可调用 API、事件流和审计产物的最小系统。

### 3. 接入真实 AgentScope 2 运行时

项目依赖固定为 `agentscope==2.0.1`，并通过以下模块接入：

- `as2_adapter.py`：检测 AS2 包、解析模型 provider、映射本地事件和权限模式。
- `as2_runtime.py`：构建真实 AS2 `Agent`、`OpenAIChatModel`、`OpenAICredential`、`Toolkit`、`AgentState`、`PermissionContext` 和 `ReActConfig`。
- `as2_openai.py`：处理 OpenAI-compatible provider 调用。

当前运行时支持 DeepSeek 的 OpenAI-compatible API。没有 provider key 时，系统会自动退回 deterministic planner，因此测试、demo 和 benchmark 不依赖真实模型也能完整跑通。API key 只作为运行时环境变量使用，不写入代码、日志或审计产物。

### 4. 做出了静态审计前端

前端位于 `frontend/`，由 `index.html`、`styles.css`、`app.js` 组成。它支持：

- 设置 API 地址。
- 选择权限模式。
- 创建 planner run。
- 查看历史 run。
- 通过 SSE 实时显示事件 timeline。
- 读取并展示 `audit.md`。

这个前端让后端能力可以直接演示，而不是只能通过命令行验证。

### 5. 实现了 baseline 和优化 planner

项目现在支持两种 planner strategy：

- `greedy_topk`：baseline，按候选 action 的分数独立排序，取前 5 个。
- `audit_astar`：优化版，使用受限 A* 风格搜索，在候选工具/action path 上综合风险、权限摩擦、重复动作、证据覆盖和目标 gap 来选择路径。

`audit_astar` 位于 `backend/openclaw/search_planner.py`。它会记录 `search_started`、`search_expand`、`search_score`、`search_prune`、`search_selected` 等搜索事件，因此优化过程本身也能进入审计报告。

### 6. 建立了 planner benchmark 体系

我实现了本地 benchmark harness：

- `backend/openclaw/benchmark.py`
- `benchmarks/tasks/*.json`
- `data/benchmarks/{timestamp}/metrics.json`
- `data/benchmarks/{timestamp}/report.md`

任务设计借鉴 PlanBench、AgentBench、WebArena、TravelPlanner、tau-bench、API-Bank、ToolBench 和 StableToolBench，但保留在本地 deterministic 环境里，方便重复运行和稳定比较。

当前 benchmark suite 由 7 个 JSON 文件展开为 24 个任务，覆盖：

- workspace grounding
- permission trap
- tool path
- safety
- production safety
- ambiguity

并区分 dev / holdout split，避免只在调参任务上证明效果。

### 7. 取得了可量化的 benchmark 结果

最新本地 benchmark 结果位于：

- `data/benchmarks/20260618T091019Z/report.md`
- `data/benchmarks/20260618T091019Z/metrics.json`

关键结果：

| Strategy | Success rate | Mean score | Mean latency | Invalid tools | Hallucinated actions | Loop failures | Unsafe auto-allow |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `audit_astar` | 100.00% | 1.0000 | 0.3255s | 0 | 0 | 0 | 0 |
| `greedy_topk` | 20.83% | 0.7361 | 0.2833s | 0 | 0 | 0 | 0 |

在 holdout split 上：

| Strategy | Success rate | Mean score | Mean latency |
| --- | ---: | ---: | ---: |
| `audit_astar` | 100.00% | 1.0000 | 0.3470s |
| `greedy_topk` | 33.33% | 0.7963 | 0.2823s |

也就是说，当前 evidence 支持这样的结论：在本地 deterministic planner benchmark 上，`audit_astar` 明显优于 `greedy_topk`，并且没有引入 invalid tool、hallucinated action、loop failure 或 unsafe auto-allow 回归。

### 8. 补齐了测试覆盖

测试位于 `tests/`，覆盖：

- planner 主流程。
- permission gate。
- AS2 adapter 和 runtime。
- backend server endpoint。
- search planner。
- benchmark runner。

这使得项目不只是能跑 demo，也能用单元测试保护关键行为。

### 9. 整理了项目文档和发布历史

当前已有文档包括：

- `README.md`：项目定位、架构、运行方式、benchmark 结果和当前 Capstone fit。
- `docs/MVP_PLAN.md`：MVP 设计与实现顺序。
- `docs/AS2_ARCHITECTURE.md`：AS2 运行时架构和代码映射。
- `docs/CAPSTONE_PLANNER_RESEARCH.md`：Planner 方向研究论证。
- `docs/PLANNER_BENCHMARKS.md`：benchmark 设计、指标、stop criteria 和当前结果。

此外，临时 Git checkout `/tmp/openclaw_optimization_push` 中可以看到该实现已经按模块化提交发布过，当前 `main`、`ltc` 和对应远端引用指向合并后的 `f0e9497 Merge planner optimization from ltc`。

## 当前项目能展示什么

现在这个 repo 可以展示三件关键事情：

1. 有系统：可以启动后端和前端，创建 planner run，流式查看事件，读取审计报告。
2. 有架构：AS2 runtime、OpenClaw planner、permission gate、storage、audit、frontend API 边界清晰。
3. 有证据：benchmark 有任务集、dev/holdout split、重复运行、metrics、report 和 stop criteria。

## 当前边界和还没完成的部分

这个项目目前还不是完整三方向 Capstone 的最终形态：

- Strategist/model routing 还没有真正实现，只是 provider 配置已经集中，后续可以加 RouteLLM/FrugalGPT 风格 router。
- Architect/progressive context 还没有完整 memory/retrieval/compaction，只是 workspace 和 audit boundary 已经打好。
- `audit_astar` 是 A* 风格的 bounded search，不是完整 LATS/MCTS。
- 当前最强 benchmark 证据来自 deterministic runtime，model-backed AS2 重复实验还需要在稳定 provider 配置下继续跑。

## 下一步建议

如果继续推进，优先级可以是：

1. 增加 model-backed AS2 benchmark，在 DeepSeek/OpenAI-compatible provider 上重复跑 dev/holdout。
2. 把 `audit_astar` 和 `greedy_topk` 的差异写成 Capstone 实验章节。
3. 添加 `audit_lats` 或 MCTS-lite 作为 stretch planner。
4. 扩展任务集，加入更贴近真实 OpenClaw 工作流的 repo-grounded 多步任务。
5. 如果需要覆盖三方向，再补 Strategist 的模型路由和 Architect 的渐进式上下文注入。

## 可复现实验命令

启动后端：

```bash
scripts/start_backend.sh
```

启动前端：

```bash
scripts/start_frontend.sh
```

运行测试：

```bash
.venv/bin/python -m unittest discover -s tests
```

运行默认 benchmark：

```bash
.venv/bin/python backend/openclaw/benchmark.py --repeats 3
```

只跑 holdout：

```bash
.venv/bin/python backend/openclaw/benchmark.py --split holdout --repeats 3
```

启用 A* planner：

```bash
OPENCLAW_PLANNER_STRATEGY=audit_astar scripts/start_backend.sh
```

启用 DeepSeek OpenAI-compatible AS2 runtime：

```bash
DEEPSEEK_API_KEY=... scripts/start_backend.sh
```
