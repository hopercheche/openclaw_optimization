# Planner 设计通俗讲解

这份文档对应问答：「关于整个 planner 的设计，Codex 做了什么，由浅入深、通俗地讲解」。

## 一句话版

Codex 做的不是“再写一个 agent”，而是给 OpenClaw agent 外面加了一层 Planner：让 agent 在真正行动前，先生成多种可选步骤，比较哪条路径更安全、更有证据、更符合目标，然后再经过权限检查执行，并把全过程记录成审计报告。

## 浅层理解

普通 agent 很像“看到任务就一步一步往前做”。问题是它可能会：

- 选错工具；
- 漏掉关键步骤；
- 遇到危险操作时不该自动执行却执行了；
- 做完以后很难解释为什么这么做。

所以 Planner 的设计目标就是：

> 先规划，再行动；先判断风险，再执行；边做边记录证据。

可以把它理解成给 agent 装了一个“任务导航系统”。不是直接冲出去做事，而是先看地图、比较路线、避开危险路段，必要时停下来问人。

## 中层：整个 Planner 的主流程

Planner 主流程在 `backend/openclaw/planner.py`，核心类叫 `LocalAuditPlanner`。

一次 run 大概这样走：

1. 接收用户目标，比如“帮我规划一个可审计的自动化任务”。
2. 记录 `run_started`，创建这次任务的状态。
3. 做 `goal_analysis`，分析目标、权限模式、planner strategy。
4. 生成候选步骤，也就是 agent 可能会做的若干 action。
5. 调用 search planner，从候选步骤里选一条最合适的路径。
6. 对每一步做 reasoning，说明为什么要做。
7. 进入 permission gate，判断这一步是 `allow`、`ask` 还是 `deny`。
8. 如果允许，就模拟执行 tool。
9. 如果需要人工确认，就进入 `human_gate`。
10. 如果被拒绝，就记录 blocked 和 critique。
11. 每一步都写事件日志。
12. 最后生成 `final_response` 和 `audit.md` 审计报告。

也就是说，Codex 做的是一条完整链路：

```text
目标输入
  -> 候选动作
  -> 路径选择
  -> 权限判断
  -> 工具执行/拦截
  -> 反思检查
  -> 审计报告
```

## 再深一点：Planner 真正优化的地方

真正的优化点在 `backend/openclaw/search_planner.py`。

这里实现了三个 strategy：

| Strategy | 作用 | 通俗解释 |
| --- | --- | --- |
| `greedy_topk` | baseline，按候选 action 分数取前几个 | 只看眼前每一步哪个分数高 |
| `audit_astar` | bounded A* 风格搜索，选择整体更优 action path | 先比较多条路线，再选最稳的一条 |
| `audit_reflexion` | 在 A* path 基础上做复查和修正 | 出发前再检查有没有漏工具、漏安全步骤 |

### `greedy_topk`

`greedy_topk` 是 baseline。它很简单：给每个候选 action 打分，然后选分数最高的几个。

它的问题是只看单个动作好不好，不太看“组合起来是不是一条好路径”。所以在复杂任务里，它可能选到一堆看起来分数不错、但组合后漏掉关键工具的步骤。

### `audit_astar`

`audit_astar` 是优化版。它用 bounded A* 风格搜索，不是只看单步，而是搜索一串 action path。

它会考虑：

- 这个步骤对目标有没有帮助；
- 能不能提供 evidence；
- 风险高不高；
- 是否可逆；
- 是否会触发权限问题；
- 有没有重复做同类动作；
- 有没有覆盖任务需要的工具。

所以它选的不是“眼前分数最高的动作”，而是“整体更安全、更完整、更可审计的一条路径”。

### `audit_reflexion`

`audit_reflexion` 是再往上一层的反思版。它先用 `audit_astar` 选路径，然后再做一次确定性的 review/repair。

如果发现路径里缺了安全步骤、工具覆盖不完整、或者顺序不够好，就补充或调整，并记录 `reflection_*` 事件。

这样不只是结果可审计，连“为什么修正路径”也可审计。

## 更深：为什么叫 audit-first

这个 Planner 的核心不是“让模型自由发挥”，而是“所有动作都要留下证据”。

Codex 设计了事件流，每一步都会被记录，比如：

- `run_started`
- `goal_analysis`
- `candidate_step`
- `search_started`
- `search_expand`
- `search_score`
- `search_selected`
- `reasoning`
- `permission`
- `tool_call`
- `tool_result`
- `critique`
- `human_gate`
- `final`
- `run_completed`

这些事件最后会被保存成：

- `events.jsonl`
- `state.json`
- `audit.md`

通俗讲，Planner 不只是“做事情”，还会写清楚：

> 我为什么想做这一步、这一步风险是什么、权限是否允许、结果是什么、有没有被拦截。

## AgentScope 2 怎么接进来

Codex 还做了 AgentScope 2 的集成边界，说明在 `docs/AS2_ARCHITECTURE.md`。

这里的设计很克制：

- AgentScope/model 可以负责提出候选 plan；
- 但模型不能绕过权限；
- 模型不能直接决定危险操作；
- 所有步骤仍然要进 OpenClaw 的 permission gate；
- 所有结果仍然要落到 audit 里。

这样做的好处是既能利用大模型/AgentScope 的规划能力，又不会把安全边界交出去。

## 怎么证明 Planner 有用

Codex 不只是写了设计，还做了 benchmark。说明和结果在 `docs/PLANNER_BENCHMARKS.md` 和 `docs/EXPERIMENT_RESULTS_TABLES_CN.md`。

benchmark 做的事情是：拿同一批任务，让不同 planner strategy 去跑，然后比较成功率、分数、安全问题、延迟和审计事件。

最新主实验中：

| Strategy | Success rate | Mean score | 安全回归 |
| --- | ---: | ---: | --- |
| `greedy_topk` | 5.68% | 0.7528 | 0 |
| `audit_astar` | 100.00% | 1.0000 | 0 |
| `audit_reflexion` | 100.00% | 1.0000 | 0 |

这说明当前本地 benchmark 下，优化 planner 明显比贪心 baseline 稳定，而且没有引入安全回归。

## 汇报版总结

我负责的 Planner 方向，主要是用 Codex 实现了一套 audit-first planner layer。它不是直接让 agent 执行任务，而是先生成候选步骤，再通过 A* 风格搜索选择整体更优的 action path，然后经过权限门控执行，并把每一步 reasoning、permission、tool result 和 critique 都记录下来。后续我又加入了 reflexion-style path review，让 planner 能在执行前修正路径。最后通过本地 benchmark 对比 `greedy_topk` baseline 和优化策略，证明 `audit_astar` / `audit_reflexion` 在任务成功率上明显更好，同时保持安全审计指标没有回归。
