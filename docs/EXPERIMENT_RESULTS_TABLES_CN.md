# Planner 实验数据汇总表与解释

这份文档汇总 OpenClawPOpti 当前可读取到的 Planner 实验数据。主数据源是仓库内的 `data/benchmarks`、`data/model_matrix` 和 `data/planner_models`；另外补充了两个仍存在于 `/tmp` 的 no-hint generalization smoke 结果，用来解释 learned profile model 的作用。

## 1. 结论先行

- 主实验已经从最早的 6-task smoke 扩展到 88-task、3-repeat、dev/holdout split 的正式 benchmark。
- 最新正式实验 `20260622T144217Z` 中，`audit_astar` 和 `audit_reflexion` 都达到 100.00% success rate；`greedy_topk` 只有 5.68%。
- 最新正式实验中，三个策略的 invalid tool、hallucinated action、loop failure、unsafe auto-allow 全部为 0，说明优化策略没有引入这些安全回归。
- `audit_reflexion` 和 `audit_astar` 成功率相同，但平均 search events 更少，并额外记录 reflection events，说明它在保持结果的同时加入了可审计的路径复查。
- no-hint generalization smoke 显示：去掉显式 profile/tool hints 后，不启用 learned profile model 时 `audit_astar` 成功率只有 5.88%；启用后达到 97.06%，holdout 为 100.00%。
- model-matrix smoke 主要验证 provider 配置、缺失环境变量检测和 fallback/skip 统计；因为没有 provider key，不能把它解释为真实模型质量对比。

## 2. 指标口径说明

| 指标 | 解释 |
| --- | --- |
| task_count | 唯一 benchmark 任务数量。 |
| repeat_count | 每个 strategy 对同一任务重复运行的次数。 |
| summary.tasks | 实际运行记录数，通常等于 task_count × repeat_count；每个 strategy 单独统计。 |
| success_rate | 满足任务约束的运行比例。 |
| mean_score | 软评分均值，会因缺少期望工具、缺少事件或安全问题被扣分。 |
| mean_latency_seconds | 平均运行耗时，单位秒。 |
| mean_event_count | 平均每次 run 产生的事件数量。 |
| mean_reasoning_steps | 平均 reasoning/action 步数。 |
| mean_search_event_count | search planner 记录的平均搜索事件数，反映路径搜索和审计密度。 |
| mean_reflection_event_count | `audit_reflexion` 记录的平均反思/修正事件数。 |
| permission_intervention_count | `ask` 或 `deny` 等权限介入次数。 |
| invalid_tool_call_count | 实际调用了未知工具的次数。 |
| hallucinated_action_count | 选择或调用不存在动作/工具的次数。 |
| loop_failure_count | 重复动作造成循环失败的次数。 |
| unsafe_auto_allow_count | 本应拦截的危险动作被自动允许的次数。 |
| model_started/result/fallback/skipped | AS2/model runtime 是否尝试调用、是否产出候选、是否 fallback、是否因无 key 跳过。 |

注意：表里的 `运行次数` 指每个 strategy 的实际运行记录数，不是不同任务数量。例如最新实验 88 个任务、重复 3 次，因此单个 strategy 的 `运行次数` 是 264。

## 3. 仓库内 Planner Benchmark 总览

| 实验目录 | 创建时间 | Runtime | 唯一任务数 | 重复次数 | Split | 策略 | Stop criteria | 核心结果 | 源文件 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 20260618T074451Z | 2026-06-18 07:44:54 | - | 6 | - | - | greedy_topk, audit_astar | - | astar 100.00%; greedy 33.33% | data/benchmarks/20260618T074451Z/metrics.json |
| 20260618T084839Z | 2026-06-18 08:49:22 | - | 24 | 3 | - | greedy_topk, audit_astar | 是 | astar 100.00%; greedy 20.83% | data/benchmarks/20260618T084839Z/metrics.json |
| 20260618T091019Z | 2026-06-18 09:11:04 | deterministic | 24 | 3 | {'dev': 15, 'holdout': 9} | greedy_topk, audit_astar | 是 | astar 100.00%; greedy 20.83% | data/benchmarks/20260618T091019Z/metrics.json |
| 20260622T033223Z | 2026-06-22 03:33:28 | deterministic | 24 | 3 | {'dev': 15, 'holdout': 9} | greedy_topk, audit_astar, audit_reflexion | 是 | astar 100.00%; reflexion 100.00%; greedy 20.83% | data/benchmarks/20260622T033223Z/metrics.json |
| 20260622T113013Z | 2026-06-22 11:32:50 | deterministic | 54 | 3 | {'dev': 35, 'holdout': 19} | greedy_topk, audit_astar, audit_reflexion | 是 | astar 92.59%; reflexion 92.59%; greedy 9.26% | data/benchmarks/20260622T113013Z/metrics.json |
| 20260622T113343Z | 2026-06-22 11:36:18 | deterministic | 54 | 3 | {'dev': 35, 'holdout': 19} | greedy_topk, audit_astar, audit_reflexion | 是 | astar 100.00%; reflexion 100.00%; greedy 9.26% | data/benchmarks/20260622T113343Z/metrics.json |
| 20260622T132039Z | 2026-06-22 13:23:01 | deterministic | 54 | 3 | {'dev': 35, 'holdout': 19} | greedy_topk, audit_astar, audit_reflexion | 是 | astar 100.00%; reflexion 100.00%; greedy 9.26% | data/benchmarks/20260622T132039Z/metrics.json |
| 20260622T140830Z | 2026-06-22 14:12:17 | deterministic | 88 | 3 | {'dev': 61, 'holdout': 27} | greedy_topk, audit_astar, audit_reflexion | 是 | astar 100.00%; reflexion 100.00%; greedy 5.68% | data/benchmarks/20260622T140830Z/metrics.json |
| 20260622T143035Z | 2026-06-22 14:34:21 | deterministic | 88 | 3 | {'dev': 61, 'holdout': 27} | greedy_topk, audit_astar, audit_reflexion | 是 | astar 89.77%; reflexion 89.77%; greedy 5.68% | data/benchmarks/20260622T143035Z/metrics.json |
| 20260622T144217Z | 2026-06-22 14:46:03 | deterministic | 88 | 3 | {'dev': 61, 'holdout': 27} | greedy_topk, audit_astar, audit_reflexion | 是 | astar 100.00%; reflexion 100.00%; greedy 5.68% | data/benchmarks/20260622T144217Z/metrics.json |

解释：这张表展示实验规模的演进。早期 `20260618T074451Z` 只是 6 个任务的 smoke；后续扩展到 24 个任务并加入 holdout；6 月 22 日继续加入 PhoneHarness、多源 generalization、`audit_reflexion`，最终形成 88-task 主实验。

## 4. 所有 Benchmark Run × Strategy 指标表

| 实验目录 | Strategy | 运行次数 | Success | Mean score | Latency(s) | Events | Reasoning | Search events | Reflection events | 权限介入 | Invalid tools | Hallucinated | Loop failures | Unsafe auto-allow |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 20260618T074451Z | audit_astar | 6 | 100.00% | 1.0000 | 0.3123 | 158.1667 | 5 | 121 | - | - | 0 | 0 | 0 | 0 |
| 20260618T074451Z | greedy_topk | 6 | 33.33% | 0.7778 | 0.2888 | 39 | 5 | 0 | - | - | 0 | 0 | 0 | 0 |
| 20260618T084839Z | audit_astar | 72 | 100.00% | 1.0000 | 0.3152 | 158.5833 | 5 | 121 | - | 75 | 0 | 0 | 0 | 0 |
| 20260618T084839Z | greedy_topk | 72 | 20.83% | 0.7361 | 0.2818 | 39 | 5 | 0 | - | 0 | 0 | 0 | 0 | 0 |
| 20260618T091019Z | audit_astar | 72 | 100.00% | 1.0000 | 0.3255 | 158.5833 | 5 | 121 | - | 75 | 0 | 0 | 0 | 0 |
| 20260618T091019Z | greedy_topk | 72 | 20.83% | 0.7361 | 0.2833 | 39 | 5 | 0 | - | 0 | 0 | 0 | 0 | 0 |
| 20260622T033223Z | audit_astar | 72 | 100.00% | 1.0000 | 0.3128 | 158.5833 | 5 | 121 | 0 | 75 | 0 | 0 | 0 | 0 |
| 20260622T033223Z | audit_reflexion | 72 | 100.00% | 1.0000 | 0.2932 | 137.5833 | 5 | 97 | 3 | 75 | 0 | 0 | 0 | 0 |
| 20260622T033223Z | greedy_topk | 72 | 20.83% | 0.7361 | 0.2805 | 39 | 5 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 20260622T113013Z | audit_astar | 162 | 92.59% | 0.9722 | 0.3472 | 161.4444 | 5 | 121 | 0 | 87 | 0 | 0 | 0 | 0 |
| 20260622T113013Z | audit_reflexion | 162 | 92.59% | 0.9722 | 0.3303 | 141.7778 | 5 | 97 | 4.3333 | 87 | 0 | 0 | 0 | 0 |
| 20260622T113013Z | greedy_topk | 162 | 9.26% | 0.7438 | 0.2832 | 41.2222 | 5 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 20260622T113343Z | audit_astar | 162 | 100.00% | 1.0000 | 0.3426 | 161.3704 | 5 | 121 | 0 | 99 | 0 | 0 | 0 | 0 |
| 20260622T113343Z | audit_reflexion | 162 | 100.00% | 1.0000 | 0.3251 | 141.4815 | 5 | 97 | 4.1111 | 99 | 0 | 0 | 0 | 0 |
| 20260622T113343Z | greedy_topk | 162 | 9.26% | 0.7438 | 0.2833 | 41.2222 | 5 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 20260622T132039Z | audit_astar | 162 | 100.00% | 1.0000 | 0.2924 | 98.0370 | 4.9074 | 58.1296 | 0 | 99 | 0 | 0 | 0 | 0 |
| 20260622T132039Z | audit_reflexion | 162 | 100.00% | 1.0000 | 0.2942 | 92.0370 | 5 | 47.4630 | 4.2037 | 99 | 0 | 0 | 0 | 0 |
| 20260622T132039Z | greedy_topk | 162 | 9.26% | 0.7438 | 0.2848 | 41.2222 | 5 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 20260622T140830Z | audit_astar | 264 | 100.00% | 1.0000 | 0.2773 | 78 | 4.7727 | 38.5909 | 0 | 120 | 0 | 0 | 0 | 0 |
| 20260622T140830Z | audit_reflexion | 264 | 100.00% | 1.0000 | 0.2892 | 77.0909 | 5 | 32.0455 | 4.5000 | 120 | 0 | 0 | 0 | 0 |
| 20260622T140830Z | greedy_topk | 264 | 5.68% | 0.7528 | 0.2838 | 41.1705 | 5 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 20260622T143035Z | audit_astar | 264 | 89.77% | 0.9688 | 0.2739 | 65.7045 | 4.7727 | 25.7500 | 0 | 111 | 0 | 0 | 0 | 0 |
| 20260622T143035Z | audit_reflexion | 264 | 89.77% | 0.9688 | 0.2887 | 67.7500 | 5 | 21.9318 | 4.7273 | 111 | 0 | 0 | 0 | 0 |
| 20260622T143035Z | greedy_topk | 264 | 5.68% | 0.7528 | 0.2861 | 41.6591 | 5 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 20260622T144217Z | audit_astar | 264 | 100.00% | 1.0000 | 0.2778 | 78.3182 | 4.7727 | 38.5909 | 0 | 120 | 0 | 0 | 0 | 0 |
| 20260622T144217Z | audit_reflexion | 264 | 100.00% | 1.0000 | 0.2902 | 77.4091 | 5 | 32.0455 | 4.5000 | 120 | 0 | 0 | 0 | 0 |
| 20260622T144217Z | greedy_topk | 264 | 5.68% | 0.7528 | 0.2846 | 41.4886 | 5 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

解释：`greedy_topk` 一直是对照组，成功率从 33.33% 降到 5.68%，主要因为任务集越来越复杂；`audit_astar` 在任务扩展后仍能恢复到 100.00%；`audit_reflexion` 在 6 月 22 日加入后与 `audit_astar` 持平，同时额外提供路径复查证据。

## 5. 最新正式实验 `20260622T144217Z` 详细表

| Split | Strategy | 运行次数 | Success | Mean score | Latency(s) | Events | Search events | Reflection events | 权限介入 | Invalid tools | Hallucinated | Loop failures | Unsafe auto-allow |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| all | audit_astar | 264 | 100.00% | 1.0000 | 0.2778 | 78.3182 | 38.5909 | 0 | 120 | 0 | 0 | 0 | 0 |
| all | audit_reflexion | 264 | 100.00% | 1.0000 | 0.2902 | 77.4091 | 32.0455 | 4.5000 | 120 | 0 | 0 | 0 | 0 |
| all | greedy_topk | 264 | 5.68% | 0.7528 | 0.2846 | 41.4886 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| dev | audit_astar | 183 | 100.00% | 1.0000 | 0.2718 | 75.1311 | 35.5574 | 0 | 96 | 0 | 0 | 0 | 0 |
| dev | audit_reflexion | 183 | 100.00% | 1.0000 | 0.2847 | 74.9180 | 29.6557 | 4.5410 | 96 | 0 | 0 | 0 | 0 |
| dev | greedy_topk | 183 | 3.28% | 0.7432 | 0.2846 | 41.4754 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| holdout | audit_astar | 81 | 100.00% | 1.0000 | 0.2913 | 85.5185 | 45.4444 | 0 | 24 | 0 | 0 | 0 | 0 |
| holdout | audit_reflexion | 81 | 100.00% | 1.0000 | 0.3026 | 83.0370 | 37.4444 | 4.4074 | 24 | 0 | 0 | 0 | 0 |
| holdout | greedy_topk | 81 | 11.11% | 0.7747 | 0.2847 | 41.5185 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

### 最新实验 Stop Criteria 检查

| 检查项 | 结果 |
| --- | --- |
| has_required_strategies | 是 |
| task_count_ok | 是 |
| repeat_count_ok | 是 |
| holdout_evaluated | 是 |
| holdout_task_count | 27 |
| holdout_task_count_ok | 是 |
| success_delta | 0.9432 |
| success_delta_ok | 是 |
| mean_score_delta | 0.2472 |
| mean_score_delta_ok | 是 |
| holdout_success_delta | 0.8889 |
| holdout_success_delta_ok | 是 |
| holdout_mean_score_delta | 0.2253 |
| holdout_mean_score_delta_ok | 是 |
| latency_ratio | 0.9761 |
| latency_ratio_ok | 是 |
| no_safety_regression | 是 |

解释：最新实验的核心证据不是只看总体成功率，而是同时看 dev 和 holdout。`audit_astar` / `audit_reflexion` 在 holdout 上也达到 100.00%，说明不是只对 dev 调参有效。`latency_ratio=0.9761` 表示 `audit_astar` 没有比 greedy 慢到不可接受；同时安全类计数全为 0。

## 6. No-hint Generalization Smoke：学习型 Profile Model 的作用

| 条件 | 源文件 | 唯一任务数 | 重复次数 | Split | Success | Mean score | Latency(s) | Search events | 权限介入 | Invalid tools | Unsafe auto-allow |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 关闭 learned profile model | /tmp/openclaw_stripped_no_model/metrics.json | 34 | 1 | {'dev': 26, 'holdout': 8} | 5.88% | 0.7917 | 0.3735 | 121 | 5 | 0 | 0 |
| 启用 learned profile model | /tmp/openclaw_stripped_with_model/metrics.json | 34 | 1 | {'dev': 26, 'holdout': 8} | 97.06% | 0.9902 | 0.2845 | 11 | 7 | 0 | 0 |

| 条件 | Split | 运行次数 | Success | Mean score | Latency(s) | Search events |
| --- | --- | --- | --- | --- | --- | --- |
| 关闭 learned profile model | dev | 26 | 7.69% | 0.7949 | 0.3772 | 121 |
| 关闭 learned profile model | holdout | 8 | 0.00% | 0.7812 | 0.3615 | 121 |
| 启用 learned profile model | dev | 26 | 96.15% | 0.9872 | 0.2844 | 12.0385 |
| 启用 learned profile model | holdout | 8 | 100.00% | 1.0000 | 0.2849 | 7.6250 |

解释：这个实验把任务里的显式 `planner_profile` / `execution_tool(s)` hint 去掉，测试 planner 是否还能从任务文本判断该用什么工具。关闭 learned profile model 时，planner 基本回到缺工具状态，成功率只有 5.88%；启用后成功率达到 97.06%，holdout 为 100.00%。这说明 profile model 不是锦上添花，而是在没有显式 hint 时帮助 planner 找回正确工具路径。

## 7. Model Matrix Smoke 表

| Matrix run | Entry | Runtime | Strategy | 任务数 | 重复次数 | Split | Env ready | 缺失 env | Success | Mean score | Latency(s) | Model started | Model result | Fallback | Skipped |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 20260622T030951Z | deterministic_baseline | deterministic | audit_astar | - | 1 | holdout | 是 | - | 100.00% | 1.0000 | 0.3311 | 0 | 0 | 0 | 9 |
| 20260622T030951Z | deterministic_baseline | deterministic | greedy_topk | - | 1 | holdout | 是 | - | 33.33% | 0.7963 | 0.2880 | 0 | 0 | 0 | 9 |
| 20260622T030951Z | as2_deepseek_flash | as2 | audit_astar | - | 1 | holdout | 否 | DEEPSEEK_API_KEY | 100.00% | 1.0000 | 0.3302 | 0 | 0 | 0 | 9 |
| 20260622T030951Z | as2_deepseek_flash | as2 | greedy_topk | - | 1 | holdout | 否 | DEEPSEEK_API_KEY | 33.33% | 0.7963 | 0.2819 | 0 | 0 | 0 | 9 |
| 20260622T030951Z | as2_openai_compatible | as2 | audit_astar | - | 1 | holdout | 否 | OPENAI_API_KEY | 100.00% | 1.0000 | 0.3340 | 0 | 0 | 0 | 9 |
| 20260622T030951Z | as2_openai_compatible | as2 | greedy_topk | - | 1 | holdout | 否 | OPENAI_API_KEY | 33.33% | 0.7963 | 0.2827 | 0 | 0 | 0 | 9 |
| 20260622T030951Z | as2_dashscope_qwen | as2 | audit_astar | - | 1 | holdout | 否 | DASHSCOPE_API_KEY | 100.00% | 1.0000 | 0.3313 | 0 | 0 | 0 | 9 |
| 20260622T030951Z | as2_dashscope_qwen | as2 | greedy_topk | - | 1 | holdout | 否 | DASHSCOPE_API_KEY | 33.33% | 0.7963 | 0.2811 | 0 | 0 | 0 | 9 |
| 20260622T031111Z | deterministic_baseline | deterministic | audit_astar | 9 | 1 | holdout | 是 | - | 100.00% | 1.0000 | 0.3599 | 0 | 0 | 0 | 9 |
| 20260622T031111Z | deterministic_baseline | deterministic | greedy_topk | 9 | 1 | holdout | 是 | - | 33.33% | 0.7963 | 0.2860 | 0 | 0 | 0 | 9 |
| 20260622T031111Z | as2_deepseek_flash | as2 | audit_astar | 9 | 1 | holdout | 否 | DEEPSEEK_API_KEY | 100.00% | 1.0000 | 0.3622 | 0 | 0 | 0 | 9 |
| 20260622T031111Z | as2_deepseek_flash | as2 | greedy_topk | 9 | 1 | holdout | 否 | DEEPSEEK_API_KEY | 33.33% | 0.7963 | 0.3127 | 0 | 0 | 0 | 9 |
| 20260622T031111Z | as2_openai_compatible | as2 | audit_astar | 9 | 1 | holdout | 否 | OPENAI_API_KEY | 100.00% | 1.0000 | 0.3291 | 0 | 0 | 0 | 9 |
| 20260622T031111Z | as2_openai_compatible | as2 | greedy_topk | 9 | 1 | holdout | 否 | OPENAI_API_KEY | 33.33% | 0.7963 | 0.2812 | 0 | 0 | 0 | 9 |
| 20260622T031111Z | as2_dashscope_qwen | as2 | audit_astar | 9 | 1 | holdout | 否 | DASHSCOPE_API_KEY | 100.00% | 1.0000 | 0.3345 | 0 | 0 | 0 | 9 |
| 20260622T031111Z | as2_dashscope_qwen | as2 | greedy_topk | 9 | 1 | holdout | 否 | DASHSCOPE_API_KEY | 33.33% | 0.7963 | 0.2816 | 0 | 0 | 0 | 9 |

解释：model matrix 的重点是验证“配置矩阵能跑、缺 key 能被识别、模型调用统计能被记录”。表中 AS2 entries 因为缺少 `DEEPSEEK_API_KEY` / `OPENAI_API_KEY` / `DASHSCOPE_API_KEY`，所以 model 都是 skipped。这些结果不能说明 DeepSeek/OpenAI/DashScope 的效果，只能说明 fallback 和 skip 机制正常。

## 8. AS2 Key Smoke 补充

| 源文件 | Runtime | Provider | Model | 唯一任务数 | 运行次数 | Success | Mean score | Latency(s) | Model started | Model result | Fallback | Skipped | Model events |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| /tmp/openclaw_as2_key_smoke/metrics.json | as2 | deepseek | deepseek-v4-flash | 1 | 1 | 0.00% | 0.9167 | 22.3895 | 1 | 1 | 0 | 0 | 42 |

解释：这个 smoke 证明在有 DeepSeek key 时，AS2 model-backed path 确实能启动并返回候选，`model_started=1`、`model_result=1`、`model_events=42`。但它只有 1 个 dev task，且 success 为 0.00%，所以只能作为集成冒烟测试，不能作为模型质量结论。

## 9. Planner Profile Model 评估表

| Split | 样本数 | Planner profile acc | Execution tools acc | Policy mode acc | Mistake records |
| --- | --- | --- | --- | --- | --- |
| dev | 244 | 100.00% | 98.77% | 84.02% | 20 |
| holdout | 81 | 100.00% | 95.06% | 64.20% | 20 |

| 项目 | 数量/设置 |
| --- | --- |
| 总样本数 | 325 |
| Dev 样本 | 244 |
| Holdout 样本 | 81 |
| 训练/评估时是否移除显式 profile hints | 是 |
| 模型文件 | `data/planner_models/profile_policy_model.json` |
| 指标文件 | `data/planner_models/profile_policy_metrics.json` |

解释：profile model 的目标不是生成最终回答，而是给 planner 一个保守 hint：当任务没有显式 `execution_tool(s)=...` 时，预测任务属于哪类 planner profile、应该覆盖哪些 execution tools、policy mode 是 act/confirm/refuse 哪一种。它对 planner profile 和 execution tools 的预测很稳，但 policy mode 在 holdout 上只有 64.20%，说明安全策略判断仍然需要继续依赖显式规则和 permission gate，而不能完全交给这个模型。

## 10. 怎么给老师解释这些实验

可以按三层讲：

1. **Baseline 对比**：`greedy_topk` 是简单贪心，只看单步分数；`audit_astar` 看的是整条工具路径，所以在复杂任务集里成功率明显更高。
2. **安全和审计**：优化 planner 没有以牺牲安全为代价。最新实验中 invalid tool、hallucinated action、loop failure、unsafe auto-allow 都是 0，而且 search/reflection events 让路径选择过程可复盘。
3. **泛化能力**：no-hint smoke 说明 learned profile model 能在没有显式工具标签时恢复大部分正确 routing，但 policy mode 仍是短板，所以最终系统仍保留 permission gate。

## 11. 局限性

- 正式主实验是 deterministic runtime，不等于真实 provider-backed AS2 大模型质量。
- model matrix 中 provider key 缺失，所以只验证了配置和 fallback 机制，没有验证真实模型表现。
- AS2 key smoke 只有 1 个任务，只能证明链路打通，不能证明效果。
- `/tmp` 下的 no-hint smoke 是临时 artifact，建议后续复制到 `data/benchmarks` 或 `data/experiments` 作为正式证据。
- profile model 的 policy-mode holdout accuracy 只有 64.20%，因此安全策略不能只依赖学习模型。

## 12. Source Inventory

| 类型 | 路径 |
| --- | --- |
| benchmark | data/benchmarks/20260618T074451Z/metrics.json |
| benchmark | data/benchmarks/20260618T084839Z/metrics.json |
| benchmark | data/benchmarks/20260618T091019Z/metrics.json |
| benchmark | data/benchmarks/20260622T033223Z/metrics.json |
| benchmark | data/benchmarks/20260622T113013Z/metrics.json |
| benchmark | data/benchmarks/20260622T113343Z/metrics.json |
| benchmark | data/benchmarks/20260622T132039Z/metrics.json |
| benchmark | data/benchmarks/20260622T140830Z/metrics.json |
| benchmark | data/benchmarks/20260622T143035Z/metrics.json |
| benchmark | data/benchmarks/20260622T144217Z/metrics.json |
| model_matrix | data/model_matrix/20260622T030951Z/matrix_metrics.json |
| model_matrix | data/model_matrix/20260622T031111Z/matrix_metrics.json |
| profile_model | data/planner_models/profile_policy_metrics.json |
| profile_model_report | data/planner_models/profile_policy_report.md |
| tmp_no_hint_control | /tmp/openclaw_stripped_no_model/metrics.json |
| tmp_no_hint_with_model | /tmp/openclaw_stripped_with_model/metrics.json |
| tmp_as2_key_smoke | /tmp/openclaw_as2_key_smoke/metrics.json |
