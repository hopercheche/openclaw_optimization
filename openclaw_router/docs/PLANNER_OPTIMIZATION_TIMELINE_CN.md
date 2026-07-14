# Planner 渐进优化时间线

这份时间线用通俗口径解释 Planner 方向是怎么一步一步变强的。核心脉络可以概括成：

> 先让 agent 能跑并留下证据，再加入搜索式规划；然后扩大任务集、加入反思修正、接入真实 workflow 数据；最后用 profile model 解决没有显式工具提示时的泛化问题。

## 总览版

| 阶段 | 时间/证据 | 当时的问题 | 做了什么优化 | 效果 |
| --- | --- | --- | --- | --- |
| 1. 先搭出可运行链路 | `backend/openclaw/planner.py`, `docs/MVP_PLAN.md` | 只有 planner 想法，还不能完整演示。 | 搭建 `LocalAuditPlanner`、REST/SSE API、事件流、权限门控、`audit.md`。 | 从概念变成可运行、可审计的原型。 |
| 2. 建 baseline 和第一个 A* planner | `20260618T074451Z` | 需要证明 planner 比简单贪心好。 | 做 `greedy_topk` baseline，并实现 `audit_astar`。 | 6-task smoke：`audit_astar` 100.00%，`greedy_topk` 33.33%。 |
| 3. 从 smoke 变成正式 benchmark | `20260618T084839Z`, `20260618T091019Z` | 6 个任务太少，不足以汇报。 | 扩到 24 个任务，加入 3 repeats、dev/holdout split、stop criteria。 | 24-task：`audit_astar` 100.00%，`greedy_topk` 20.83%；holdout 也成立。 |
| 4. 加入 Reflexion 复查 | `20260622T033223Z` | A* 能选路径，但缺少“执行前复查/修正”的证据。 | 新增 `audit_reflexion`：先跑 A*，再做 deterministic reflection repair。 | `audit_reflexion` 100.00%，同时记录 `reflection_*` 事件。 |
| 5. 接入 PhoneHarness workflow | `20260622T113013Z` | 原始任务偏本地 repo 场景，不够接近真实移动端/工具流。 | 转换 PhoneHarness 任务，加入 GUI、CLI、MCP、安全策略任务。 | 任务扩到 54 个，难度上升；优化策略一度降到 92.59%，暴露工具覆盖问题。 |
| 6. 修复 profile/tool 覆盖 | `20260622T113343Z` | 新任务需要正确覆盖 `mobile_gui_runner`、`mobile_cli_runner`、`mcp_tool_runner`、`safety_guard`。 | 用 `planner_profile` / `execution_tool(s)` 信息指导 desired tools。 | 54-task 恢复到 `audit_astar` / `audit_reflexion` 100.00%。 |
| 7. 减少搜索成本 | `20260622T132039Z` | A* 每次都展开很多节点，审计很全但有点重。 | 加入 profile-aligned shortcut：如果目标工具很明确，直接走覆盖路径，同时保留 search 事件。 | `audit_astar` search events 从 121 降到 58.1296，成功率仍 100.00%。 |
| 8. 做多源泛化 suite | `20260622T140830Z` | 不能只证明 PhoneHarness；要覆盖更多 agent/task 类型。 | 加入 tau2、ToolBench、SkillsBench，构建 88-task 多源 benchmark。 | 88-task：`audit_astar` / `audit_reflexion` 100.00%，`greedy_topk` 5.68%。 |
| 9. 训练 learned profile model | `profile_policy_metrics.json`, `/tmp/openclaw_stripped_*` | 如果任务没有显式工具提示，planner 可能不知道该选哪类工具。 | 用 325 个样本训练 Naive Bayes profile model，预测 planner profile、execution tools、policy mode。 | no-hint：关闭模型 5.88%，启用模型 97.06%，holdout 100.00%。 |
| 10. 最终主实验验证 | `20260622T144217Z` | 需要一组稳定、可报告的最终证据。 | 88 tasks × 3 repeats，比较 `greedy_topk`、`audit_astar`、`audit_reflexion`。 | 两个优化策略 100.00%，greedy 5.68%；安全指标全为 0；stop criteria met。 |

## 通俗讲解版

### 第一阶段：先把“想法”变成“能跑的系统”

最开始 Planner 只是一个方向：我们希望 agent 不要看到任务就直接乱做，而是先规划。Codex 首先做的是把这个想法落成一条完整运行链路。

这一步做出的东西包括：

- 用户发起一个任务；
- 后端创建一个 run；
- planner 生成候选步骤；
- 每一步进入权限判断；
- 允许的步骤执行，不允许的步骤拦截；
- 全过程写入事件日志；
- 最后生成 `audit.md` 审计报告。

通俗地说，这一步是先给 agent 装上“行车记录仪”和“刹车系统”。它不一定已经最聪明，但每一步做了什么、为什么做、有没有被权限拦住，都能看见。

### 第二阶段：建立 baseline，再证明 A* search 有用

有了系统之后，下一步就是证明“planner 优化”真的比普通策略好。于是 Codex 做了两个策略：

- `greedy_topk`：简单贪心，只看单个候选步骤分数高不高。
- `audit_astar`：A* 风格搜索，不只看单步，而是看一整条 action path 是否更安全、更完整、更有证据。

早期 6-task smoke 的结果是：

| 实验 | 任务数 | `greedy_topk` | `audit_astar` |
| --- | ---: | ---: | ---: |
| `20260618T074451Z` | 6 | 33.33% | 100.00% |

这个阶段要讲的重点是：  
`greedy_topk` 像“每一步都选眼前最高分”，而 `audit_astar` 像“先看整条路线，再决定怎么走”。这就是 Planner 优化的第一层价值。

### 第三阶段：把小实验变成正式实验

6 个任务只能说明链路有希望，但不够作为汇报证据。于是 Codex 把 benchmark 扩展到 24 个任务，并加入：

- 3 repeats；
- dev / holdout split；
- stop criteria；
- success rate、mean score、latency、安全指标。

24-task 结果：

| 实验 | 任务数 | Split | `greedy_topk` | `audit_astar` |
| --- | ---: | --- | ---: | ---: |
| `20260618T091019Z` | 24 | dev 15 / holdout 9 | 20.83% | 100.00% |

这一步的优化不是某个算法小技巧，而是实验方法变严谨了。它回答的是：“这不是碰巧在几个 toy task 上有效，而是在重复运行和 holdout 上也有效。”

### 第四阶段：加入 Reflexion，让 planner 会复查自己

`audit_astar` 能选路径，但它更像一次性搜索。为了让系统有“执行前复查”的能力，Codex 加了 `audit_reflexion`。

它的逻辑是：

1. 先让 `audit_astar` 选出一条路径；
2. 再检查这条路径有没有缺安全步骤、缺目标工具、顺序不合理；
3. 如果有问题，就做 deterministic repair；
4. 把复查过程写成 `reflection_started`、`reflection_issue`、`reflection_refined` 等事件。

结果：

| 实验 | `greedy_topk` | `audit_astar` | `audit_reflexion` |
| --- | ---: | ---: | ---: |
| `20260622T033223Z` | 20.83% | 100.00% | 100.00% |

通俗地说，`audit_reflexion` 相当于 planner 做完路线规划后，又自己检查一遍：“有没有忘带工具？有没有漏安全门？有没有顺序不对？”

### 第五阶段：加入 PhoneHarness，让任务更像真实 workflow

原来的任务更偏本地 repo、权限、安全、工具路径。为了让 Planner 更贴近真实 agent workflow，Codex 接入了 PhoneHarness 数据。

PhoneHarness 带来了更复杂的任务类型：

- 手机 GUI 操作；
- 手机 CLI / ADB / shell 类操作；
- MCP 风格工具调用；
- 需要先确认或拒绝的安全任务。

任务扩到 54 个之后，第一次结果变成：

| 实验 | 任务数 | `greedy_topk` | `audit_astar` | `audit_reflexion` |
| --- | ---: | ---: | ---: | ---: |
| `20260622T113013Z` | 54 | 9.26% | 92.59% | 92.59% |

这个下降很重要。它说明任务变真实以后，planner 不能只靠原来的本地规则，需要更明确地知道“这个任务应该用哪类 execution tool”。

### 第六阶段：用 profile/tool hint 修复工具覆盖问题

PhoneHarness 暴露的问题是：Planner 有时候知道要完成任务，但没有稳定覆盖正确工具。例如移动端任务可能必须包含：

- `mobile_gui_runner`
- `mobile_cli_runner`
- `mcp_tool_runner`
- `safety_guard`

于是 Codex 加了 profile/tool-aware routing：如果任务里出现 `planner_profile` 或 `execution_tool(s)`，planner 会把这些工具纳入 desired tools，并优先规划覆盖这些工具的路径。

修复后：

| 实验 | 任务数 | `greedy_topk` | `audit_astar` | `audit_reflexion` |
| --- | ---: | ---: | ---: | ---: |
| `20260622T113343Z` | 54 | 9.26% | 100.00% | 100.00% |

通俗讲，这一步是给 planner 加了“任务类型识别”。以前它知道要规划，现在它进一步知道：“这是手机 GUI 任务”“这是 MCP 工具任务”“这是安全确认任务”。

### 第七阶段：减少搜索成本，让 planner 更轻

A* search 很完整，但早期平均 search events 很高，常见是 121。审计信息很全，但搜索有点重。

于是 Codex 加了 profile-aligned shortcut：  
如果任务已经明确暴露了应该使用哪些工具，而且候选步骤都能覆盖，那么 planner 不必暴力展开很多等价路径，可以直接选择覆盖路径，同时保留关键 search 事件。

对比：

| 实验 | 任务数 | Strategy | Success | Search events |
| --- | ---: | --- | ---: | ---: |
| `20260622T113343Z` | 54 | `audit_astar` | 100.00% | 121 |
| `20260622T132039Z` | 54 | `audit_astar` | 100.00% | 58.1296 |
| `20260622T132039Z` | 54 | `audit_reflexion` | 100.00% | 47.4630 |

这一步的意思是：不仅要做对，还要更高效地做对。

### 第八阶段：从单一数据源扩展到多源泛化

只靠 PhoneHarness 还不够，因为它主要代表移动端/workflow 类型。Codex 接着把任务扩展到多源：

- PhoneHarness：移动 GUI/CLI/MCP 和安全策略；
- tau2：带 domain policy 的工具 agent；
- ToolBench：API planning；
- SkillsBench：文件编辑、命令验证等 skill workflow。

任务扩展到 88 个：

| 实验 | 任务数 | Split | `greedy_topk` | `audit_astar` | `audit_reflexion` |
| --- | ---: | --- | ---: | ---: | ---: |
| `20260622T140830Z` | 88 | dev 61 / holdout 27 | 5.68% | 100.00% | 100.00% |

这一步是从“某一类任务做得好”，推进到“多类 agent/workflow 任务上也能做得好”。

### 第九阶段：训练 learned profile model，解决没有 hint 的情况

前面 profile/tool hint 很有效，但有一个现实问题：真实用户请求里不一定会写 `execution_tool=...`。所以 Codex 又训练了一个轻量 profile model。

它用 325 个样本训练，来源包括：

- 30 个 PhoneHarness；
- 184 个 tau2；
- 100 个 ToolBench；
- 11 个 SkillsBench。

模型学三件事：

- 任务属于哪类 planner profile；
- 应该覆盖哪些 execution tools；
- policy mode 更像 act、confirm 还是 refuse。

模型评估：

| Split | Planner profile acc | Execution tools acc | Policy mode acc |
| --- | ---: | ---: | ---: |
| dev | 100.00% | 98.77% | 84.02% |
| holdout | 100.00% | 95.06% | 64.20% |

最关键的是 no-hint smoke：

| 条件 | 任务数 | Success | Holdout success |
| --- | ---: | ---: | ---: |
| 关闭 learned profile model | 34 | 5.88% | 0.00% |
| 启用 learned profile model | 34 | 97.06% | 100.00% |

通俗讲，这一步是让 planner 在用户没有明说“该用什么工具”的时候，也能大致判断任务类型和工具路线。

### 第十阶段：最终主实验收敛

最后一轮主实验是 `20260622T144217Z`：

| Strategy | Success | Mean score | Latency | Search events | Reflection events | 安全问题 |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `greedy_topk` | 5.68% | 0.7528 | 0.2846s | 0 | 0 | 0 |
| `audit_astar` | 100.00% | 1.0000 | 0.2778s | 38.5909 | 0 | 0 |
| `audit_reflexion` | 100.00% | 1.0000 | 0.2902s | 32.0455 | 4.5000 | 0 |

holdout 上：

| Strategy | Holdout success |
| --- | ---: |
| `greedy_topk` | 11.11% |
| `audit_astar` | 100.00% |
| `audit_reflexion` | 100.00% |

这一轮说明：最终 Planner 不只是能在 dev 上跑好，在 holdout 上也保持 100.00%；同时 invalid tool、hallucinated action、loop failure、unsafe auto-allow 都是 0。

## 最适合汇报的一段话

我在 Planner 方向的优化是渐进式推进的。最开始只是把 agent 执行过程做成可运行、可审计的链路；然后建立 `greedy_topk` baseline，并用 `audit_astar` 证明搜索式规划比单步贪心更可靠。接着我把实验从 6 个 smoke task 扩到 24 个正式 benchmark task，并加入 dev/holdout 和 stop criteria。之后我加入 `audit_reflexion`，让 planner 在执行前能自查和修正路径。再往后，我接入 PhoneHarness、tau2、ToolBench 和 SkillsBench，让任务从本地场景扩展到移动端、MCP、API planning 和 skill workflow。过程中我发现复杂任务需要更稳定的工具覆盖，所以加入 profile/tool-aware routing 和 profile-aligned shortcut，在保持 100.00% 成功率的同时显著减少搜索事件。最后，为了解决真实任务没有显式工具 hint 的问题，我训练了 learned profile model，使 no-hint 任务成功率从 5.88% 提升到 97.06%。最终主实验在 88 个任务、3 次重复、dev/holdout split 下，`audit_astar` 和 `audit_reflexion` 都达到 100.00% success rate，而 `greedy_topk` 只有 5.68%，并且安全回归指标全部为 0。

## 一句话总结

这条优化路线不是一次性“堆算法”，而是一步步解决真实 planner 会遇到的问题：先能跑，再能审计，再比 baseline 强，再能复查，再能处理真实 workflow，再能泛化到没有显式工具提示的任务。
