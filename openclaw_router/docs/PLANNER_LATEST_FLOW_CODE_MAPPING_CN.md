# 最新 Planner 完整流程与代码映射

这份文档对应问答：「最新的完整流程通俗的语言讲清楚，并且要有到代码的映射」。

## 总览

最新版 Planner 流程可以这样讲：

> 用户提交一个目标后，系统不会直接执行，而是先创建一次 run，分析目标，生成候选动作，再用 planner strategy 选出一条最合适的路径。然后每一步都经过权限门控：安全的自动执行，危险的暂停询问或拒绝。整个过程会持续写入事件流，最后生成 `state.json`、`events.jsonl` 和 `audit.md`，方便复盘和证明。

一句话：

> 它是一个“先规划、再检查权限、再执行/拦截、最后审计留证”的 agent planner。

## 完整流程图

```text
POST /api/runs
  -> RunManager.create_run
  -> PlannerThread
  -> LocalAuditPlanner.run
  -> run_started / goal_analysis
  -> AS2 model candidates or deterministic candidates
  -> select_planner_path
       -> greedy_topk
       -> audit_astar
       -> audit_reflexion
  -> reasoning per selected step
  -> PermissionEngine.decide
       -> allow
       -> ask / human_gate
       -> deny
  -> simulated tool_call / tool_result
  -> critique
  -> final response
  -> run_completed
  -> write audit.md
  -> frontend/API reads events and audit
```

## 1. 用户请求进来

用户通过 API 发起：

```json
{
  "goal": "...",
  "permission_mode": "DEFAULT",
  "planner_strategy": "audit_reflexion"
}
```

代码映射：

| 功能 | 代码 |
| --- | --- |
| `POST /api/runs` 入口 | `backend/openclaw/server.py` 的 `OpenClawHandler.do_POST()` |
| 读取并校验 `goal` | `server.py` 中 `goal = str(payload.get("goal", "")).strip()` |
| 校验 `permission_mode` | `server.py` 中 `permission_mode not in {"DEFAULT", "EXPLORE", "ACCEPT_EDITS", "BYPASS", "DONT_ASK"}` |
| 校验 `planner_strategy` | `server.py` 中 `planner_strategy not in SUPPORTED_PLANNER_STRATEGIES` |

通俗讲，这一步就是后端先确认：“你要做什么？你允许我做到什么程度？你想用哪种 planner？”

## 2. 创建一次 run

系统创建 `RunState`，里面保存：

- `run_id`
- `goal`
- `permission_mode`
- `workspace_path`
- `planner_strategy`
- AS2 是否可用

代码映射：

| 功能 | 代码 |
| --- | --- |
| 创建 run | `backend/openclaw/server.py` 的 `RunManager.create_run()` |
| 规范化 planner strategy | `normalize_planner_strategy(...)` |
| 创建 `RunState` | `RunState(...)` |
| 持久化初始状态 | `self.storage.create_run(state)` |
| 创建 planner | `LocalAuditPlanner(...)` |
| 异步启动 | `PlannerThread(planner, state).start()` |

通俗讲，这一步是给任务生成一个档案袋。之后所有事件、状态和审计报告都会放到这个档案袋里。

## 3. Planner 开始记录审计事件

真正的主流程在：

```text
backend/openclaw/planner.py
LocalAuditPlanner.run()
```

一开始它会写两个事件：

- `run_started`：这次 run 被接收；
- `goal_analysis`：记录目标、权限模式、planner strategy。

代码映射：

| 功能 | 代码 |
| --- | --- |
| Planner 主流程入口 | `LocalAuditPlanner.run()` |
| 保存 running 状态 | `self.storage.save_state(state)` |
| 写 `run_started` | `self._emit(state, "run_started", ...)` |
| 写 `goal_analysis` | `self._emit(state, "goal_analysis", ...)` |

通俗讲，这一步就是给任务建档：谁来了、要做什么、用什么权限、用哪种 planner。

## 4. 生成候选动作

接下来系统生成候选步骤，也就是 agent 可能会做的若干 action。

代码映射：

| 情况 | 代码 |
| --- | --- |
| 候选生成入口 | `LocalAuditPlanner._generate_candidates_from_runtime()` |
| 没有模型 key，走本地 fallback | `if not self.as2_status.model_ready: ... return self._generate_candidates(state.goal)` |
| 有模型 key，走 AS2/model | `generate_as2_openai_plan(...)` |
| 本地候选生成 | `LocalAuditPlanner._generate_candidates()` |

本地候选包括：

| 工具 | 作用 |
| --- | --- |
| `goal_analyzer` | 明确任务边界 |
| `workspace_inspector` | 安全检查 workspace |
| `planner` | 生成规划 |
| `risk_model` | 做权限/风险判断 |
| `verifier` | 检查结果 |
| `file_writer` | 需要改文件时使用 |
| `command_runner` | 需要跑测试/命令时使用 |
| `deploy_runner` | 部署相关任务使用 |
| `mobile_gui_runner` | 手机 GUI workflow |
| `mobile_cli_runner` | 手机 CLI/ADB workflow |
| `mcp_tool_runner` | MCP 风格工具调用 |
| `safety_guard` | 外部 workflow 安全检查 |

外部 workflow 候选在：

```text
backend/openclaw/planner.py
_external_workflow_candidates(...)
```

通俗讲，这一步不是直接决定做什么，而是先把“可能的行动菜单”列出来。

## 5. 判断任务需要哪些工具

最新版优化里很关键的一步是：planner 不只是生成候选动作，还会判断这个任务“应该覆盖哪些工具”。

代码映射：

| 功能 | 代码 |
| --- | --- |
| 判断 desired tools | `backend/openclaw/search_planner.py` 的 `_desired_tools_for_goal()` |
| 读取显式 `execution_tool(s)=...` | `_profile_execution_tools_for_goal()` |
| 使用 learned model 预测工具 | `_learned_execution_tools_for_goal()` |
| 移动端/MCP 启发式工具判断 | `_mobile_execution_tools_for_goal()` |
| policy mode 判断 | `_learned_policy_mode_for_goal()` |

例如：

- 普通读任务：需要 `goal_analyzer`、`workspace_inspector`、`planner`、`risk_model`、`verifier`；
- 修改/测试任务：需要 `file_writer`、`command_runner`；
- 部署任务：需要 `deploy_runner`；
- 手机/MCP workflow：需要 `mobile_gui_runner`、`mobile_cli_runner`、`mcp_tool_runner`；
- 安全敏感任务：需要 `safety_guard`。

通俗讲，这一步是在问：“这个任务要成功，工具箱里哪些工具必须带上？”

## 6. 选择 planner strategy

候选动作生成后，会进入：

```text
backend/openclaw/search_planner.py
select_planner_path(...)
```

现在支持三种策略：

| Strategy | 代码类 | 作用 |
| --- | --- | --- |
| `greedy_topk` | `GreedyTopKPlannerStrategy` | baseline，按分数取前几个 |
| `audit_astar` | `AuditAStarPlannerStrategy` | A* 风格路径搜索 |
| `audit_reflexion` | `AuditReflexionPlannerStrategy` | A* 路径 + 反思修正 |

## 7. baseline：`greedy_topk`

`greedy_topk` 很简单：

> 把候选动作按分数排序，取前 5 个。

代码映射：

```text
backend/openclaw/search_planner.py
GreedyTopKPlannerStrategy.select()
```

它的问题是只看单步，不看路径整体。所以在复杂任务里，可能会漏掉必须的工具，比如安全检查、文件写入、命令验证、MCP 工具等。

## 8. 优化版：`audit_astar`

`audit_astar` 是现在的核心优化策略。

代码映射：

```text
backend/openclaw/search_planner.py
AuditAStarPlannerStrategy.select()
```

它的思路是：

> 不只看“哪个动作单独分数最高”，而是搜索“一整条动作路径”。

它会考虑：

- 当前路径覆盖了哪些工具；
- 还缺哪些 desired tools；
- 每个动作风险多大；
- 是否需要人工确认；
- 是否重复动作；
- 证据价值够不够；
- 路径是否太长。

核心代码点：

| 功能 | 代码 |
| --- | --- |
| 开始搜索并记录 `search_started` | `self._record(trace, "search_started", ...)` |
| 建立 root node | `_SearchNode(...)` |
| priority queue/frontier | `heapq.heappush(frontier, ...)` |
| 展开节点 | `while frontier and expanded < self.max_expansions:` |
| 记录 `search_expand` | `self._record(trace, "search_expand", ...)` |
| 剪枝重复 action | `search_prune` |
| 计算权限成本 | `self.permission_engine.decide(...)` |
| 计算 transition cost | `_transition_cost(...)` |
| 计算 action value | `_action_value(...)` |
| 记录 `search_score` | `self._record(trace, "search_score", ...)` |
| 记录最终选择 | `search_selected` |

通俗讲：`audit_astar` 像导航系统，不是只看下一步最近，而是比较多条路线，选一条整体最稳的路线。

## 9. 最新优化：profile-aligned shortcut

如果任务已经明确说明需要哪些工具，比如 MCP、mobile GUI、safety guard，那么没必要展开很多等价搜索节点。

于是 `audit_astar` 加了 profile-aligned shortcut。

代码映射：

```text
backend/openclaw/search_planner.py
AuditAStarPlannerStrategy._select_profile_aligned_path(...)
```

它会检查：

- 任务有没有显式 execution hints；
- 或 learned profile model 是否预测出工具；
- desired tools 是否都能被候选步骤覆盖。

如果能覆盖，就直接选一条覆盖路径，同时仍然写：

- `search_expand`
- `search_score`
- `search_selected`

这就是为什么后期实验里 search events 从 121 降到 38 左右，但成功率还能保持 100%。

## 10. 反思版：`audit_reflexion`

`audit_reflexion` 是在 `audit_astar` 后面再加一层路径复查。

代码映射：

```text
backend/openclaw/search_planner.py
AuditReflexionPlannerStrategy.select()
```

它的流程是：

1. 先跑 `audit_astar`；
2. 拿到 A* 选出的路径；
3. 检查路径是否缺 `risk_model`、`verifier`、目标工具、安全工具；
4. 如果任务是只读，就移除 mutating steps；
5. 如果缺工具，就插入；
6. 最后重新排序、裁剪到最大深度；
7. 写入 `reflection_started`、`reflection_issue`、`reflection_refined`。

代码映射：

| 功能 | 代码 |
| --- | --- |
| 先跑 A* | `base = self.astar.select(candidates, state)` |
| 开始 reflection | `_append_trace(trace, "reflection_started", ...)` |
| 只读任务移除修改步骤 | `_remove_mutating_steps(...)` |
| 确保风险检查工具 | `_ensure_tool(..., "risk_model", ...)` |
| 确保目标工具覆盖 | `for tool_name in _reflection_tool_order(desired_tools)` |
| 确保 verifier | `_ensure_tool(..., "verifier", ...)` |
| 重新排序 | `_order_reflection_path(...)` |
| 裁剪长度 | `_trim_reflection_path(...)` |
| 记录修正结果 | `reflection_refined` |

通俗讲：

> `audit_astar` 是“规划路线”，`audit_reflexion` 是“出发前再检查路线有没有漏安全门、漏工具、顺序不对”。

## 11. 每一步都过权限门控

路径选好后，`LocalAuditPlanner` 会按顺序执行每个 step。每一步先写 `reasoning`，再调用 permission engine。

代码映射：

| 功能 | 代码 |
| --- | --- |
| 遍历选中步骤 | `for index, step in enumerate(selected, start=1):` |
| 写 reasoning | `self._emit(state, "reasoning", ...)` |
| 权限判断 | `self.permission_engine.decide(step, state.permission_mode)` |
| 写 permission 事件 | `self._emit(state, "permission", ...)` |

权限判断在：

```text
backend/openclaw/permissions.py
PermissionEngine.decide(...)
```

规则很直观：

| 情况 | 结果 |
| --- | --- |
| 只读工具且不改 workspace | `allow` |
| `EXPLORE` 模式下修改动作 | `deny` |
| `DONT_ASK` 模式下不确定或修改动作 | `deny` |
| 动作含危险词，如 delete、production、secret、联系人、短信、照片 | `ask` |
| `BYPASS` 模式 | `allow` |
| `ACCEPT_EDITS` 且是 mutating tool | `allow` |
| `DEFAULT` 下修改动作 | `ask` |

所以 Planner 不是“想执行就执行”。它必须先过 `allow / ask / deny` 这道门。

## 12. `allow`、`ask`、`deny` 三种结果

权限结果会决定后续动作。

代码映射：

| 结果 | 行为 | 代码 |
| --- | --- | --- |
| `deny` | 记录 blocked，写 critique，不执行 | `if decision.behavior == "deny": ...` |
| `ask` | 写 `human_gate`，需要人类确认，不自动执行 | `if decision.behavior == "ask": ...` |
| `allow` | 写 `tool_call`，模拟执行，再写 `tool_result` 和 `critique` | `self._simulate_tool(...)` |

对应文件：

```text
backend/openclaw/planner.py
LocalAuditPlanner.run()
```

## 13. 工具执行目前是安全模拟

现在的 MVP 不是真的去删文件、发邮件、操作手机，而是模拟工具执行并产生证据文本。

代码映射：

```text
backend/openclaw/planner.py
LocalAuditPlanner._simulate_tool(...)
```

模拟内容包括：

| 工具 | 模拟结果 |
| --- | --- |
| `workspace_inspector` | 列 workspace 可见文件 |
| `planner` | 返回 planner 路径说明 |
| `risk_model` | 返回权限证据 |
| `verifier` | 返回检查结果 |
| `safety_guard` | 返回安全检查证据 |
| `mobile_gui_runner` | 返回移动 GUI workflow 模拟证据 |
| `mobile_cli_runner` | 返回移动 CLI/ADB workflow 模拟证据 |
| `mcp_tool_runner` | 返回 MCP workflow 模拟证据 |

这样做的好处是 benchmark 可重复，也避免真实副作用。

## 14. AS2/model-backed 路径怎么接入

AS2 检测和 provider 配置在：

```text
backend/openclaw/as2_adapter.py
```

支持：

- `DEEPSEEK_API_KEY`
- `OPENAI_API_KEY`
- `DASHSCOPE_API_KEY`

代码映射：

| 功能 | 代码 |
| --- | --- |
| 解析 provider key | `resolve_model_provider_config()` |
| 检测 AgentScope 2 是否可用 | `detect_as2()` |
| 映射 OpenClaw event 到 AS2 event | `LOCAL_TO_AS2_EVENT` / `map_local_event_to_as2()` |

如果有 key，`model_ready=True`，Planner 会调用：

```text
backend/openclaw/as2_runtime.py
generate_as2_openai_plan(...)
```

AS2 runtime 注册了四个只读工具：

| AS2 工具 | 作用 |
| --- | --- |
| `openclaw_audit_schema` | 告诉模型候选 plan 的 JSON schema |
| `openclaw_workspace_inventory` | 安全查看 workspace 边界 |
| `openclaw_permission_probe` | 预估某个 action 会被 allow/ask/deny |
| `openclaw_score_candidate` | 按 OpenClaw 规则给候选动作评分 |

这些工具在：

```text
backend/openclaw/as2_runtime.py
build_openclaw_as2_toolkit(...)
```

重点是：

> AS2/model 只负责提出候选计划，OpenClaw 仍然负责权限和审计。

## 15. 事件怎么保存

每次写事件都会走：

```text
backend/openclaw/planner.py
LocalAuditPlanner._emit(...)
```

`_emit()` 会：

1. 给事件分配 `event_id`；
2. 映射成 AS2 event type；
3. 写入 storage；
4. 更新 run state；
5. 通知 SSE 前端。

事件和 run 的读取接口在：

```text
backend/openclaw/server.py
OpenClawHandler._handle_run_get(...)
```

SSE 实时流在：

```text
backend/openclaw/server.py
OpenClawHandler._send_sse(...)
```

## 16. 最后生成 `audit.md`

Planner 完成后，会生成最终回答，然后写 `run_completed`，再把所有事件渲染成 Markdown audit report。

代码映射：

| 功能 | 代码 |
| --- | --- |
| 生成最终回答 | `state.final_response = self._final_response(...)` |
| 写 `final` 事件 | `self._emit(state, "final", ...)` |
| 写 `run_completed` | `self._emit(state, "run_completed", ...)` |
| 渲染 audit markdown | `render_audit_markdown(state, events)` |
| 写入 audit 文件 | `self.storage.write_audit(...)` |

用户可以通过这些 API 查看结果：

| API | 作用 |
| --- | --- |
| `GET /api/runs/{run_id}` | 查看 run 状态 |
| `GET /api/runs/{run_id}/events` | 查看全部事件 |
| `GET /api/runs/{run_id}/stream` | 实时 SSE 事件流 |
| `GET /api/runs/{run_id}/audit.md` | 查看审计报告 |

## 最适合汇报时说的一段

最新版 Planner 的完整流程是：用户提交目标后，后端先创建一个 run，并记录目标、权限模式和 planner strategy。然后系统生成候选动作，如果有 AS2/model key 就让模型提出候选，否则使用 deterministic fallback。接着 search planner 根据策略选择路径：`greedy_topk` 是 baseline，`audit_astar` 会搜索整条 action path，`audit_reflexion` 会在 A* 路径基础上再做反思修正。选出的每一步都必须经过 permission gate，判断是自动允许、需要人类确认，还是拒绝执行。允许的步骤会产生模拟工具结果，不允许的步骤会被记录为 blocked 或 human_gate。整个过程会持续写入事件流，最后生成 `audit.md`，所以不仅能看到结果，还能复盘每一步为什么被选择、为什么被允许或拦截。
