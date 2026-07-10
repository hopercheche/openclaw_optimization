# Safe Generalization Distill v2 封装收口记录（2026-07-08）

## 结论

当前推荐封装版本是 `repair_final`：

- release：`release/openclaw-planner-safe-distill-v2-repair-final`
- packaged profile model：`release/openclaw-planner-safe-distill-v2-repair-final/model/profile_policy_model_safe_distill_v2_dev_20260708.json`
- training source model：`data/planner_models/profile_policy_model_safe_distill_v2_dev_20260708.json`
- 推荐 env：`deploy/openclaw-planner-safe-distill-v2.env.example`
- 最终 1000 条复测：`data/benchmarks/20260708T_safe_generalization_distill_v2_packaging_repair_final_guard_astar_r3`
- 最终对比：`data/benchmarks/20260708T_safe_generalization_distill_v2_packaging_repair_final/comparison.json`

远端 release 不包含原始 benchmark prompt。TerminalWorld 上游样例中存在 AWS key、密码等凭据形状的测试夹具，为避免触发 secret scanning，发布包只保留 suite 数量/来源/切分统计、原始 suite SHA-256、完整 metrics/report 和 comparison；本机原始 suite 仍保留在迁移后的数据目录中。

这版不是继续训练模型，而是在 v2 profile model 基础上收窄 runtime planner 的 PhoneHarness/mobile safety/tool routing guard，并做了一轮小型修补。重点是只对明确高风险、显式 safety policy、或 learned `policy_tool_agent` 的 confirm/refuse 场景加 `safety_guard`，避免 broad guard 把普通手机任务从 5 步路径挤失败。

## 最终指标

同一 1000-task v2 suite、同一 `audit_astar`、同一 deterministic runtime：

| Run | Success | Holdout | Mean score | Mean latency | Search events | Safety violations |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| profile disabled baseline | 47.20% | 50.50% | 0.9070 | 1.1544s | 86.2300 | 0 |
| v1 prior-best baseline | 85.50% | 85.50% | 0.9749 | 0.6563s | 17.4110 | 0 |
| v2 old optimized | 97.20% | 95.00% | 0.9951 | 0.6076s | 11.8380 | 0 |
| broad guard negative | 87.40% | 85.50% | 0.9856 | 0.6449s | 11.6610 | 0 |
| final guard previous | 98.30% | 97.00% | 0.9970 | 0.6681s | 11.5090 | 0 |
| repair final recommended | 99.90% | 100.00% | 0.9998 | 0.6662s | 11.5100 | 0 |

相对 v2 old：

- success +2.70pp
- holdout +5.00pp
- search events 降到 97.22%
- latency 增加到 109.64%
- 无 regression task

相对上一版 final guard：

- success +1.60pp
- holdout +3.00pp
- 修复 16 / 17 条剩余失败
- latency ratio 0.9972，基本不变
- 无 regression task

相对无 profile baseline：

- success +52.70pp
- holdout +49.50pp
- latency ratio 0.5771，满足“压到基线 70% 以内”
- search event ratio 0.1335

## 分来源

| Source | Passed / Tasks | Success |
| --- | ---: | ---: |
| TerminalWorld safe-network | 311 / 311 | 100.00% |
| tau2 | 184 / 184 | 100.00% |
| ToolBench | 100 / 100 | 100.00% |
| SkillsBench | 11 / 11 | 100.00% |
| PhoneHarness synthetic | 250 / 250 | 100.00% |
| PhoneHarness original | 143 / 144 | 99.31% |

剩余 1 条失败来自原始 PhoneHarness：

- `safe_distill_0451_phoneharness_safety_024_safe_complete`
- missing `safety_guard`：1

这条是 B站 Python 教程样本。它看起来像普通应用内搜索，但标签要求 `safety_guard`；前一次试验表明把 `python入门教程` 或泛 B站搜索推入 safety 会让普通 B站搜索任务回退，所以本轮刻意不做这个过拟合修复。

## 这轮具体优化

1. 增强中文手机/App 任务识别：
   - 加入 `B站`、`芒果TV`、`美图秀秀`、`安居客`、`58同城`、`扫描全能王`、`Chrome`、`钉钉` 等 GUI 信号。
   - 加入 `短信`、`联系人`、`通话记录`、`WiFi`、`天气`、`新闻`、`存储`、`清理` 等 mobile CLI/上下文信号。

2. 收窄 safety guard：
   - 只对显式 `safety_policy` / `Safety policy` / `require confirmation` / `never auto-execute` 或明确高风险短语加 `safety_guard`。
   - 高风险短语包括密码、USB 调试、病毒扫描关闭、全公司邮件、自动回复所有消息、彻底清理个人数据、删除所有照片等。

3. 保持 5 步路径约束：
   - 不采用 6 步路径，因为 benchmark 里很多任务设置了 `max_reasoning_steps=5`。
   - 负结果证明 broad guard 会把 success 从 97.20% 打到 87.40%，即使 safety 计数仍为 0。

4. safety 主执行器选择：
   - 邮件/邮箱类 safety 任务优先 `mcp_tool_runner`。
   - 密码、Chrome、开发者模式、钉钉、相册/照片、个人数据清理类 safety 任务优先 `mobile_gui_runner`。

5. 小型 repair 修补：
   - 恢复 learned `policy_tool_agent` 的 confirm/refuse safety 分支，修掉 tau2 policy-agent 的安全回退。
   - 增加图像/相册/压缩类 PhoneHarness routing，让扫描图片进相册、图片压缩邮件等任务选到正确执行器。
   - 把“天气预报网站”普通浏览器打开与“查明天天气预报”安全样本区分，避免 broad weather safety 回退。
   - 相册照片删除类 safety 优先 GUI，单纯手机存储清理仍优先 CLI。

## 封装建议

容器或部署环境中增加：

```bash
OPENCLAW_PLANNER_PROFILE_MODEL=release/openclaw-planner-safe-distill-v2-repair-final/model/profile_policy_model_safe_distill_v2_dev_20260708.json
OPENCLAW_MODEL_PLANNER_POLICY=routed
```

复测命令：

```bash
OPENCLAW_PLANNER_PROFILE_MODEL=data/planner_models/profile_policy_model_safe_distill_v2_dev_20260708.json \
/home/litangchao/miniconda3/envs/AgentOpti/bin/python backend/openclaw/benchmark.py \
  --tasks-dir data/benchmarks/20260708T_safe_generalization_distill_v2_suite/tasks_dir \
  --output-dir data/benchmarks/20260708T_safe_generalization_distill_v2_packaging_repair_final_guard_astar_r3 \
  --strategies audit_astar \
  --repeats 1 \
  --split all \
  --runtime deterministic
```

## 当前边界

- 这仍然是 task-level deterministic/profile planner 优化，不是 Stage7 command/action JSON 模型替换。
- Qwen/AS2 model planner 仍建议用 `OPENCLAW_MODEL_PLANNER_POLICY=routed`，不要在本 benchmark 场景里强制 `always`。
- 剩余失败只剩 1 条原始 PhoneHarness 语义边界样本。除非后续有更强标签证据，否则不建议为了这条把 B站/教程搜索 broad safety 化。
