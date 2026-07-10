# OpenClaw Planner Safe Distill v2 - repair_final

这是 OpenClaw task-level Planner 的自包含部署包。它包含经过蒸馏的 profile-policy 模型、1000 条任务的安全评测清单与完整结果、容器部署预设和 SHA-256 校验文件。

## 运行结构

- `backend/openclaw/planner_profile_model.py` 加载本包中的 profile-policy 模型。
- `backend/openclaw/planner.py` 生成确定性候选，并按 `routed` 策略决定是否请求 Qwen/AS2 候选。
- `backend/openclaw/search_planner.py` 使用 `audit_astar` 完成路径选择、执行器路由与窄化 safety guard。
- `backend/openclaw/permissions.py` 对最终步骤执行 allow、ask 或 deny 权限判定。

## 包内容

- `model/`：可直接加载的 profile-policy 模型及训练评估。
- `benchmark/`：suite 清单、完整 metrics、报告和基线比较。
- `config/planner.env.example`：宿主与容器通用的推荐环境变量。
- `docs/`：封装说明和安全容器说明。
- `manifest.json`：版本、模型路径、运行参数和最终指标。
- `SHA256SUMS`：除自身外所有发布文件的 SHA-256。

原始 benchmark prompt 不进入 release。上游 TerminalWorld 测试夹具包含 AWS key、密码等凭据形状文本；包内 `benchmark/suite_manifest.json` 保存任务数量、来源/切分统计以及原始 suite 的 SHA-256，完整评测 metrics/report 保留不变。

## 使用

在仓库根目录加载 Planner 配置：

```bash
set -a
. release/openclaw-planner-safe-distill-v2-repair-final/config/planner.env.example
set +a
```

容器部署可直接使用仓库的安全启动脚本：

```bash
scripts/openclaw_secure_docker.sh build
scripts/openclaw_secure_docker.sh run-api
```

校验发布包：

```bash
cd release/openclaw-planner-safe-distill-v2-repair-final
sha256sum -c SHA256SUMS
```

## 已验证结果

- 任务数：1000
- 总成功率：99.90%
- holdout 成功率：100.00%
- 平均延迟：0.6662 秒
- unsafe auto allow：0

这组结果来自 deterministic runtime；Qwen/AS2 保留为 routed 候选生成分支，不应把该结果解释为 1000 条任务全部调用了 Qwen。
