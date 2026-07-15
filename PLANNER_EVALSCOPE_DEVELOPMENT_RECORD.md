# OpenClaw Task Compass Planner EvalScope 完整开发记录

## 1. 记录范围

本文记录 2026-07-15 完成的 OpenClaw Planner（Task Compass）接入，包括：

- `openclaw-planner/integrations/openclaw-native` 模板及其真实发布构建流程。
- 不重新构建 OpenClaw 的单镜像 overlay 方案。
- Task Compass `before_prompt_build` hook、离线 Python router 和 embedded skills。
- EvalScope CLI harness 的启用、严格 route probe、任务级 decision 和 JSON 聚合报告。
- 五个正式数据集脚本和一个 MockLLM smoke 脚本。
- 源码测试、bundle validator、镜像、Gateway、hook 注入和 EvalScope E2E 证据。
- 本次遇到的所有主要问题、原因、解决方法和路径。
- Featurize 服务器构建、镜像传输、运行、对比和回滚方法。

本地项目根目录：

```text
/home/lenovo/code/AIE4902
```

Featurize 服务器项目根目录：

```text
/home/featurize/work/ProjectAgentScope/openclaw_optimization
```

Featurize 数据盘：

```text
/home/featurize/data
```

下文未写绝对路径的文件均相对于项目根目录。

## 2. 最终结论

### 2.1 实际目录名

需求中写的是：

```text
integrations/oepnclaw-native
```

实际源码路径为：

```text
openclaw-planner/integrations/openclaw-native
```

后续构建全部使用真实路径 `openclaw-native`。

### 2.2 插件性质

Task Compass 是 OpenClaw native runtime plugin，不是模型 provider，也不是独立 HTTP 服务。它注册：

```text
before_prompt_build hook
```

调用内嵌的标准库 Python router，并把有界 JSON advisory 追加到模型 prompt：

```text
EvalScope sample
  -> OpenClawCliHarnessRunner
  -> openclaw agent --json
  -> 常驻 OpenClaw Gateway
  -> task-compass before_prompt_build
  -> python3 route_task.py --goal <bounded prompt>
  -> <task-compass advisory="true">...</task-compass>
  -> EvalScope model bridge
  -> 固定的被测模型
  -> EvalScope score/report/experiment_report.json
```

插件不注册执行工具、不访问 API key、不访问网络，也不替代 OpenClaw 权限系统。它只提供 advisory。

### 2.3 与 Router 的关键差异

| 项目 | Router | Task Compass Planner |
|---|---|---|
| 独立 sidecar | 有 Router API | 无 |
| 模型 provider | Router provider | 原 `evalscope` provider |
| 实际切换模型 | 是 | 否 |
| `model_tier` | 映射到真实模型 | 仅 advisory 字段 |
| 主要指标 | route/model/cost | profile/policy/tier/executor/next action |
| 失败行为 | strict 时任务失败 | 原插件静默回退 baseline |

因此 Planner 报告中的 `model_tier=small/medium/large` 不能解释为实际调用了不同模型。正式五数据集脚本始终
使用同一个 `EVALSCOPE_MODEL`，token 和费用只来自该真实模型调用。

### 2.4 baseline 不受影响

baseline 镜像保持：

```text
Tag:  openclaw-baseline:2026.6.11-srcsnap
ID:   sha256:703ad0a0fa578e4b49d60852bfb55227022699b71ad56cb85bf2c4cd96775c70
Size: 797524689 bytes
```

Planner 仅在以下变量开启时生效：

```bash
OPENCLAW_PLANNER_ENABLED=true
```

未开启时 runner 不写插件 load path/entry、不重启 Planner hook、不执行 route probe，baseline 与原流程一致。

### 2.5 最终增量镜像

```text
Tag:     openclaw-planner:2026.6.11-overlay
ID:      sha256:f31a65fa4f759eb26e2db5895cd4fd8a29748c294632d9532046e292fc838da6
Size:    800816899 bytes
Base:    openclaw-baseline:2026.6.11-srcsnap
Version: 0.3.0
```

镜像增量：

```text
800816899 - 797524689 = 3292210 bytes
```

增量主要是 canonical/legacy 两套 skill、两个 JSON 模型、evaluation metadata 和 routing contract。

构建没有运行：

```text
pnpm install
npm install
pip install
OpenClaw build:docker
OpenClaw UI build
```

## 3. 组员源码版本和路径

Planner 是独立嵌套 Git 仓库：

```text
openclaw-planner/.git
```

本次验证版本：

```text
branch: main
commit: 7f619a99285bb4786844553e3965db224e23cc74
remote: https://github.com/RTPI-ltc/Task-Compass-Skill.git
```

外层仓库当前显示：

```text
?? openclaw-planner/
```

因此服务器若要重新构建，必须单独同步该仓库，或传送已经构建好的 Docker 镜像。不要提交一个没有
`.gitmodules` 的裸 gitlink。

## 4. 原生集成模板分析

### 4.1 模板文件

```text
openclaw-planner/integrations/openclaw-native/README.md
openclaw-planner/integrations/openclaw-native/index.mjs
openclaw-planner/integrations/openclaw-native/router-bridge.mjs
openclaw-planner/integrations/openclaw-native/openclaw.plugin.json
openclaw-planner/integrations/openclaw-native/package.json
```

插件声明：

```text
id: task-compass
legacyPluginIds: [route-openclaw-task]
version: 0.3.0
Node: >=22.19.0
OpenClaw: >=2026.6.11 <2026.7.0
```

baseline 运行 Node 24，OpenClaw 2026.6.11，满足约束。

### 4.2 为什么不能只复制模板目录

`router-bridge.mjs` 固定寻找：

```text
<pluginRoot>/skills/task-compass/scripts/route_task.py
```

但模板目录本身没有 `skills/`。直接把 `integrations/openclaw-native` 复制到 extension 会导致运行时
Python script `ENOENT`，插件捕获异常后静默回退 baseline planner。

完整发布 bundle 必须由组员脚本生成：

```text
openclaw-planner/scripts/build_integrations.py
```

该脚本复制模板，并加入：

```text
LICENSE
compatibility.json
skills/task-compass/*
skills/route-openclaw-task/*
scripts/route_task.py
scripts/validate_route.py
scripts/evaluate_router.py
assets/profile-policy-model.json
assets/tool-family-model.json
assets/evaluation-metrics.json
references/routing-contract.md
references/model-card.md
```

### 4.3 构建与验证入口

```text
openclaw-planner/scripts/build_integrations.py
openclaw-planner/scripts/validate_integrations.py
openclaw-planner/scripts/benchmark_integrations.py
openclaw-planner/integrations/compatibility.json
openclaw-planner/release-manifest.json
```

本次生成的 OpenClaw native bundle：

```text
task-compass-openclaw-native-v0.3.0
files: 29
archive SHA-256: d5f31d0c254f34770918649c10907d3a9a40f32ed7675e75abb7411b8c057a05
```

bundle validator：

```json
{"valid": true, "errors": []}
```

### 4.4 Hook 安全边界

`index.mjs` 注册一个 `before_prompt_build` hook，priority 20、timeout 5500 ms。`router-bridge.mjs`：

- 使用 `execFile`，不经过 shell。
- 默认 `python3`。
- router 默认 timeout 1500 ms，可配置范围 100-5000 ms。
- prompt 默认最多 12000 字符，可配置范围 256-32000。
- stdout 上限 1 MiB。
- 只传最小环境：`LANG`、`PATH`、Python encoding/bytecode 变量。
- 只保留约定 route 字段，不把任意 subprocess 输出注入 prompt。
- 失败时只记录 error category，不打印原 prompt 或 raw error。

## 5. 最终镜像构建

### 5.1 新增路径

```text
openclaw_evalscope_cli/docker/planner-overlay.Dockerfile
openclaw_evalscope_cli/build_planner_image.sh
```

### 5.2 构建流程

```text
校验 baseline 镜像和 Planner source
创建临时 build root
运行 build_integrations.py
运行 validate_integrations.py
选取 task-compass-openclaw-native-v0.3.0
Docker FROM baseline
COPY bundle 到 /opt/openclaw-plugins/task-compass
import OpenClaw plugin SDK
执行一次离线 route_task.py
校验 schema_version=1.0
删除临时 build root
```

构建期间不访问网络。

### 5.3 容器内路径

```text
/opt/openclaw-plugins/task-compass/index.mjs
/opt/openclaw-plugins/task-compass/router-bridge.mjs
/opt/openclaw-plugins/task-compass/openclaw.plugin.json
/opt/openclaw-plugins/task-compass/package.json
/opt/openclaw-plugins/task-compass/compatibility.json
/opt/openclaw-plugins/task-compass/skills/task-compass/
/opt/openclaw-plugins/task-compass/skills/route-openclaw-task/
```

核心 router：

```text
/opt/openclaw-plugins/task-compass/skills/task-compass/scripts/route_task.py
```

### 5.4 构建命令

```bash
cd /home/featurize/work/ProjectAgentScope/openclaw_optimization

export OPENCLAW_PLANNER_BASE_IMAGE=openclaw-baseline:2026.6.11-srcsnap
export OPENCLAW_PLANNER_IMAGE=openclaw-planner:2026.6.11-overlay
export OPENCLAW_PLANNER_SOURCE_DIR="$PWD/openclaw-planner"
export OPENCLAW_PLANNER_VERSION=0.3.0

bash openclaw_evalscope_cli/build_planner_image.sh
```

## 6. EvalScope Runner 改动

### 6.1 修改路径

```text
openclaw_evalscope_cli/runner.py
openclaw_evalscope_cli/run_evalscope.py
openclaw_evalscope_cli/experiment_report.py
openclaw_evalscope_cli/README.md
README.md
```

### 6.2 新增 Runner 参数

```text
planner_enabled
planner_plugin_id
planner_plugin_path
planner_config
planner_collect_decision
planner_route_script
```

对应环境变量：

```text
OPENCLAW_PLANNER_ENABLED
OPENCLAW_PLANNER_PLUGIN_ID
OPENCLAW_PLANNER_PLUGIN_PATH
OPENCLAW_PLANNER_CONFIG
OPENCLAW_PLANNER_COLLECT_DECISION
OPENCLAW_PLANNER_ROUTE_SCRIPT
```

### 6.3 setup 流程

```text
检查 Docker Compose 和 Gateway health
检查 openclaw --version
写 plugins.load.paths=/opt/openclaw-plugins/task-compass
写 plugins.entries.task-compass
重启 Gateway
再次等待 health
plugins inspect task-compass
执行安全离线 route probe
验证 schema_version=1.0
```

Planner 单独模式不写全局 `plugins.allow`，因此 baseline 默认插件不会被关闭。

### 6.4 每样本流程

```text
清理 workspace
配置 EvalScope bridge provider
使用当前 instruction 执行同一 route_task.py
截断为插件相同的 maxPromptChars
保存有界 planner decision 和 probe wall time
执行 openclaw agent --json
插件 hook 再执行 router 并把 advisory 注入模型 prompt
保存模型输出、trace、token、费用和 runner metrics
```

Runner 的 route probe 是严格的：Python router 缺失、超时或 JSON/schema 错误会让评测任务失败。这样避免
原插件的 fallback 行为把“Planner 根本没有生效”隐藏成一个看似正常的 baseline 分数。

probe 不调用 LLM、不消耗模型 token，也不访问网络。其额外 CPU 时间记录为：

```text
planner_probe_wall_time
```

正式 v1 强制：

```text
EVALSCOPE_BATCH_SIZE=1
```

不同数据集并行使用独立 Gateway/state/port。

## 7. 任务和数据集级报告

### 7.1 任务级路径

```text
model_output.metadata.runner_metrics.planner_enabled
model_output.metadata.runner_metrics.planner_config
model_output.metadata.runner_metrics.planner_decision
model_output.metadata.runner_metrics.planner_probe_wall_time
```

保存的 decision 字段：

```text
schema_version
planner_profile
planned_tools
primary_executor
policy_mode
permission_behavior
context_policy
model_tier
next_action
safety_guard
confidence
reason
```

不保存原始 prompt。

### 7.2 数据集级汇总

```text
experiment_report.json
  -> openclaw_runtime_metrics.planner
```

包含：

```text
n_tasks_with_decision
decisions_by_profile
decisions_by_policy_mode
decisions_by_model_tier
decisions_by_primary_executor
decisions_by_next_action
mean_confidence
```

`confidence` 在真实 route contract 中是对象，数据集均值使用 `confidence.overall`，不是把整个对象误当数值。

## 8. 正式评测脚本

### 8.1 公共脚本

```text
Scripts/lib/planner_common.sh
```

负责：

- 激活 `conda activate agentscope`。
- 校验 Planner overlay 镜像。
- 使用唯一 Compose project、run ID、端口、state 和 secrets。
- 使用 `flock` 阻止同一数据集重复启动。
- 生成 Planner plugin config。
- 配置模型、Judge、价格、数据集目录和缓存。
- 启动 Gateway、等待 `/healthz`、执行 `python run.py`。
- 失败时打印 Gateway 最后 200 行日志。
- 默认关闭本次 Compose 资源。

### 8.2 五个入口

| 脚本 | 数据集 | subset/config | limit | 端口 |
|---|---|---|---:|---:|
| `Scripts/planner_mmlu_pro.sh` | MMLU-Pro | `computer science` | 5 | 19111 |
| `Scripts/planner_gpqa_diamond.sh` | GPQA Diamond | 默认 | 5 | 19112 |
| `Scripts/planner_longmemeval.sh` | LongMemEval | `s`, long_context/json/con | 1 | 19113 |
| `Scripts/planner_acebench.sh` | ACEBench | `agent` | 50 | 19114 |
| `Scripts/planner_locomo.sh` | LoCoMo | `qa`, long_context | 1 | 19115 |

### 8.3 MockLLM smoke

```text
Scripts/planner_smoke.sh
```

默认：

```text
port: 19110
model: mock
eval_type: mock_llm
limit: 1
judge: rule
```

smoke 只用于验证链路，分数没有实验意义。

## 9. 运行时和输出路径

### 9.1 OpenClaw state

```text
/tmp/openclaw-eval/<user>/planner/<dataset>/<run-id>/state
/tmp/openclaw-eval/<user>/planner/<dataset>/<run-id>/secrets
/tmp/openclaw-eval/<user>/planner/locks/<dataset>.lock
```

SQLite state 不放在 `/home/featurize/work`，避免已有 `database is locked` 问题。

### 9.2 数据集和缓存

```text
EVALSCOPE_DATASET_DIR=/home/featurize/data
MODELSCOPE_CACHE=/home/featurize/data/modelscope-cache
HF_HOME=/home/featurize/data/huggingface-cache
```

Planner 专用覆盖变量：

```text
OPENCLAW_PLANNER_DATASET_DIR
OPENCLAW_PLANNER_MODELSCOPE_CACHE
OPENCLAW_PLANNER_HF_HOME
```

### 9.3 输出

正式：

```text
outputs/planner/<model-id>__<dataset>/<timestamp>/
```

smoke：

```text
outputs/planner-smoke/<model-id>__<dataset>/<timestamp>/
```

包含：

```text
configs/task_config.yaml
predictions/<model>/<dataset>_<subset>.jsonl
reviews/<model>/<dataset>_<subset>.jsonl
reports/<model>/<dataset>.json
reports/report.html
logs/eval_log.log
experiment_report.json
```

## 10. 遇到的问题与解决方法

### 10.1 需求目录拼写和真实目录不一致

需求写 `oepnclaw-native`，源码实际为 `openclaw-native`。

解决：先使用 `find` 定位实际目录，所有构建脚本使用真实路径，并在文档记录拼写差异。

### 10.2 模板目录缺少运行资产

只看模板的 5 个文件容易误判成“直接 COPY 即可”。`router-bridge.mjs` 实际依赖模板里不存在的
`skills/task-compass/scripts/route_task.py` 和模型资产。

解决：不手工拼包，调用组员权威 `build_integrations.py`，再运行 `validate_integrations.py`，Docker 只复制
验证后的 native bundle。

### 10.3 不能在已构建镜像中简单复制到 `/app/extensions`

OpenClaw 2026.6.11 的 bundled plugin registry 在全量构建时生成。运行时后放入 `/app/extensions` 的新
插件不会自动进入该 registry，Context Index 集成已经实际复现过 stale/legacy bundled path 问题。

解决：Planner overlay 使用：

```text
/opt/openclaw-plugins/task-compass
plugins.load.paths
```

若未来同时修改 OpenClaw core，才把发布后的 bundle 放入源码 extension 并全量 build。

### 10.4 源码测试因 checkout 目录名失败

首次在：

```text
/home/lenovo/code/AIE4902/openclaw-planner
```

运行 37 个组员测试，35 个通过，2 个失败：

```text
skill name 'task-compass' must match parent directory 'openclaw-planner'
```

失败测试：

```text
test_skill_schema
test_release_verifier
```

原因是 release validator 要求 repository 根目录 basename 与 skill name 相同，不是算法或 bundle 错误。

解决：复制同一 commit 到规范临时目录：

```text
/tmp/task-compass
```

重新运行后：

```text
Ran 37 tests
OK
```

正式 CI/checkout 建议直接使用目录名 `task-compass`。

### 10.5 原插件失败会静默回退 baseline

插件设计上捕获 Python missing、timeout、invalid JSON 等错误并返回空结果。这对生产可用性友好，但会使
评测误把“Planner 没生效”当成普通 baseline 结果。

解决：runner setup 和每样本都执行严格 route probe。任何 router/schema 错误直接失败，且不记录 prompt。

### 10.6 如何证明 hook 真正注入，而不只证明插件加载

`plugins inspect` 只能证明 module loaded，不能证明 `before_prompt_build` 在真实 agent call 中成功执行。

解决：MockLLM E2E 后从 bridge prediction messages 中提取：

```text
<task-compass advisory="true">
{...}
Preserve refuse, await_human, replan, confirmation, read-only, and safety constraints...
</task-compass>
```

并把该 JSON 与 runner 的离线 `planner_decision` 做结构化 equality 检查。结果：

```json
{"advisory_present": true, "probe_matches_hook": true}
```

### 10.7 `confidence` 不是标量

初始报告聚合按数值读取 `confidence`，真实 router 输出却是：

```json
{
  "overall": 0.725275,
  "planner_profile": 0.967712,
  "execution_tools": 0.999999,
  "policy_mode": 0.735385,
  "known_token_ratio": 0.725275
}
```

因此初始 smoke 的 `mean_confidence` 会显示空。

解决：报告聚合读取 `confidence.overall`，同时保留完整任务级 confidence 对象。测试改为使用真实结构。

### 10.8 不能用 Planner `model_tier` 计算真实模型费用

Task Compass 只向 prompt 注入建议，不改变 `models.providers.evalscope` 或请求 model。若按 `model_tier`
套用 Router 价格，会产生虚假的分模型费用。

解决：Planner 模式继续使用单模型 token/cost 口径；`model_tier` 只做决策分布，不进入计费公式。

### 10.9 不应设置只包含 Planner 的全局 allowlist

Context Index 集成曾发现 `plugins.allow=[context-index]` 会关闭 baseline 默认插件。Planner 若照搬也会破坏
ACEBench 工具能力。

解决：Planner 单独模式不写 `plugins.allow`。Gateway 验证：

```text
baseline: 8 plugins
planner:  9 plugins = baseline 8 + task-compass
```

### 10.10 `skills list --json` 输出很大

直接输出整个 skill catalog 超过工具显示预算。该现象不影响功能。

解决：使用结构化过滤检查 canonical 和 legacy skill；E2E bridge system context 也确认：

```text
task-compass
route-openclaw-task
```

二者均 eligible、model visible，来源为 `openclaw-extra`。

### 10.11 Planner route probe 增加一次本地 CPU 调用

为了严格审计，每样本的 Python router 会执行两次：一次由 runner probe，一次由真实 OpenClaw hook。

解决：

- probe 不产生模型 token 或外部费用。
- 单独记录 `planner_probe_wall_time`。
- 对相同截断 prompt 验证 probe 与 hook decision 完全一致。
- 可用 `OPENCLAW_PLANNER_COLLECT_DECISION=false` 关闭任务级 probe，但正式实验不建议关闭。

## 11. 验证证据

### 11.1 组员源码测试

规范目录 `/tmp/task-compass`：

```text
37 tests passed
integration bundles validate
240 integration cases exact parity = 1.0
schema validity = 1.0
safety invariant rate = 1.0
archive reproducibility passed
secret/history scan passed
```

### 11.2 外层 EvalScope 测试

新增：

```text
openclaw_evalscope_cli/tests/test_planner_config.py
openclaw_evalscope_cli/tests/test_planner_experiment_report.py
```

更新：

```text
openclaw_evalscope_cli/tests/test_router_experiment_report.py
```

Planner 实现后外层测试结果：

```text
11 passed
```

### 11.3 插件 runtime

```text
Task Compass Skill
id: task-compass
Status: loaded
Source: /opt/openclaw-plugins/task-compass/index.mjs
Version: 0.3.0
```

Gateway：

```text
http server listening
(9 plugins: browser, canvas, device-pair, file-transfer, memory-core,
 ollama, phone-control, talk-voice, task-compass)
```

### 11.4 EvalScope MockLLM E2E

本地 work dir：

```text
/tmp/openclaw-planner-smoke/eval-output/20260715_180213
```

关键产物：

```text
/tmp/openclaw-planner-smoke/eval-output/20260715_180213/configs/task_config.yaml
/tmp/openclaw-planner-smoke/eval-output/20260715_180213/predictions/openclaw_planner_mock_smoke/gsm8k_main.jsonl
/tmp/openclaw-planner-smoke/eval-output/20260715_180213/reports/openclaw_planner_mock_smoke/gsm8k.json
/tmp/openclaw-planner-smoke/eval-output/20260715_180213/reports/report.html
/tmp/openclaw-planner-smoke/eval-output/20260715_180213/experiment_report.json
```

实际 route：

```text
planner_profile: skill_workflow
policy_mode: confirm
model_tier: medium
primary_executor: file_writer
next_action: await_human
confidence.overall: 0.725275
```

`experiment_report.json` 聚合：

```json
{
  "n_tasks_with_decision": 1,
  "decisions_by_profile": {"skill_workflow": 1},
  "decisions_by_policy_mode": {"confirm": 1},
  "decisions_by_model_tier": {"medium": 1},
  "decisions_by_primary_executor": {"file_writer": 1},
  "decisions_by_next_action": {"await_human": 1},
  "mean_confidence": 0.725275
}
```

## 12. 服务器部署

### 12.1 服务器重建

```bash
cd /home/featurize/work/ProjectAgentScope/openclaw_optimization

test -f openclaw-planner/integrations/openclaw-native/openclaw.plugin.json
test -f openclaw-planner/scripts/build_integrations.py
git -C openclaw-planner rev-parse HEAD

bash openclaw_evalscope_cli/build_planner_image.sh
```

### 12.2 直接传镜像

本机：

```bash
docker save openclaw-planner:2026.6.11-overlay \
  | gzip > openclaw-planner-2026.6.11-overlay.tar.gz

scp openclaw-planner-2026.6.11-overlay.tar.gz \
  featurize@<server>:/home/featurize/work/
```

服务器：

```bash
gzip -dc /home/featurize/work/openclaw-planner-2026.6.11-overlay.tar.gz \
  | docker load

docker image inspect openclaw-planner:2026.6.11-overlay
```

加载镜像后运行不需要服务器存在 `openclaw-planner/` 源码。

### 12.3 smoke 和正式运行

```bash
cd /home/featurize/work/ProjectAgentScope/openclaw_optimization

bash Scripts/planner_smoke.sh
bash Scripts/planner_mmlu_pro.sh
bash Scripts/planner_gpqa_diamond.sh
bash Scripts/planner_longmemeval.sh
bash Scripts/planner_acebench.sh
bash Scripts/planner_locomo.sh
```

覆盖样本数：

```bash
EVALSCOPE_LIMIT=20 bash Scripts/planner_acebench.sh
```

保留失败容器：

```bash
OPENCLAW_PLANNER_KEEP_CONTAINERS=true bash Scripts/planner_acebench.sh
```

## 13. 实验比较方法

baseline 与 Planner 固定：

```text
模型及 endpoint
temperature/max_tokens/seed
数据集版本/subset/limit
Judge 策略和 Judge 模型
模型价格
OpenClaw 2026.6.11 baseline
```

比较：

```text
score
token total/avg/min/max
cost_estimate
latency
错误和超时
planner profile/policy/tier/executor/next_action 分布
confidence.overall
```

Planner 的目标是改善规划和安全决策，MMLU-Pro/GPQA 主要作为知识推理回归；ACEBench 更接近 agent/tool
规划场景。LongMemEval/LoCoMo 可以观察长输入下的 route 稳定性，但它们不是 Planner route accuracy 的
专用标注集。

Task Compass 自带的 `benchmarks/integrations-v0.3.json` 和 240-case parity 更适合验证路由 contract；五个
EvalScope 数据集用于衡量把 advisory 接入完整 OpenClaw 后的端到端质量、token、费用和行为变化。

## 14. 后续更新流程

```bash
git -C openclaw-planner status
git -C openclaw-planner rev-parse HEAD

export OPENCLAW_PLANNER_IMAGE=openclaw-planner:<experiment-id>
bash openclaw_evalscope_cli/build_planner_image.sh
bash Scripts/planner_smoke.sh
```

每次实验记录：

```text
Planner commit
native bundle SHA-256
overlay image ID
TaskConfig
模型/Judge/价格
五数据集输出目录
```

## 15. 完整改动路径清单

### 新增

```text
PLANNER_EVALSCOPE_DEVELOPMENT_RECORD.md
openclaw_evalscope_cli/docker/planner-overlay.Dockerfile
openclaw_evalscope_cli/build_planner_image.sh
Scripts/lib/planner_common.sh
Scripts/planner_smoke.sh
Scripts/planner_mmlu_pro.sh
Scripts/planner_gpqa_diamond.sh
Scripts/planner_longmemeval.sh
Scripts/planner_acebench.sh
Scripts/planner_locomo.sh
openclaw_evalscope_cli/tests/test_planner_config.py
openclaw_evalscope_cli/tests/test_planner_experiment_report.py
```

### 修改

```text
README.md
openclaw_evalscope_cli/README.md
openclaw_evalscope_cli/runner.py
openclaw_evalscope_cli/run_evalscope.py
openclaw_evalscope_cli/experiment_report.py
openclaw_evalscope_cli/tests/test_router_experiment_report.py
```

### 读取但未修改的组员路径

```text
openclaw-planner/integrations/openclaw-native/*
openclaw-planner/integrations/compatibility.json
openclaw-planner/scripts/build_integrations.py
openclaw-planner/scripts/validate_integrations.py
openclaw-planner/scripts/benchmark_integrations.py
openclaw-planner/scripts/route_task.py
openclaw-planner/assets/*
openclaw-planner/references/*
openclaw-planner/tests/*
openclaw-planner/release-manifest.json
openclaw-planner/docs/OPENCLAW_INTEGRATION.md
```

### 复用且未修改

```text
openclaw_evalscope_cli/docker-compose.evalscope.yml
openclaw-main/Dockerfile
openclaw-baseline:2026.6.11-srcsnap
```

## 16. 验收结论

- 已确认真实目录、模板结构、缺失发布资产和权威 bundle 构建路径。
- 已完成不运行 npm/pnpm/pip 的单 Gateway Planner overlay。
- 已构建并验证 `openclaw-planner:2026.6.11-overlay`。
- 已完成 runner setup、严格 probe、任务 decision 和数据集聚合报告。
- 已完成五个正式数据集脚本和 MockLLM smoke 脚本。
- 已完成组员 37/37 测试、bundle validation、外层 11 项测试和真实 E2E。
- 已证明 OpenClaw hook advisory 与 runner probe decision 完全一致。
- 已保留 baseline 默认插件和原权限系统。
- 已明确 Planner tier 不等于真实模型路由，避免错误计费解释。
