# OpenClaw CLI Harness EvalScope 开发记录

更新时间：2026-07-10

本文记录本项目中 OpenClaw 作为 EvalScope 外部 Agent CLI harness 的接入过程、镜像构建方式、服务启动方式、EvalScope 评测方式、验证结果和踩坑修复。

## 0. Python 环境与依赖

项目要求 Python 3.10 或更高版本，当前开发环境使用 Python 3.12。服务器部署时在项目根目录创建虚拟环境并安装依赖：

```bash
cd /path/to/AIE4902

python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

`requirements.txt` 中的 EvalScope 固定到本项目已经验证过的 GitHub 源码提交，以保证 `AgentRunner`、external agent bridge 等接口与当前实现一致；AgentScope 固定为 `2.0.3`，并启用示例服务需要的 FastAPI 和 Redis 依赖。

Python requirements 不负责安装以下系统组件：

- Git，用于安装固定提交的 EvalScope 源码。
- Docker Engine 和 Docker Compose plugin，用于运行 OpenClaw Gateway/CLI 容器。
- OpenClaw baseline 或 modified 镜像，需要按第 3 节单独构建。

安装后检查：

```bash
python -c "import evalscope, agentscope; print('Python dependencies: OK')"
docker compose version
```

## 1. 目标和总体方案

目标是评测 OpenClaw 本身的 CLI harness 行为，而不是只测试 OpenClaw Gateway API。

正式评测链路：

```text
EvalScope
  -> ExternalAgentConfig(framework="openclaw-cli-harness")
  -> 自定义 AgentRunner
  -> openclaw agent --json
  -> 常驻 OpenClaw Gateway
  -> EvalScope bridge
  -> 上游模型 provider
```

关键点：

- EvalScope 不直接把 `/v1/responses` 当正式评测入口。
- OpenClaw Gateway 常驻，用于承载 OpenClaw runtime、agent state、workspace、config。
- 每个样本运行前，runner 临时把 OpenClaw provider 指向 EvalScope bridge。
- 因为 provider/token 会写入同一个 OpenClaw config volume，v1 默认强制 `eval_batch_size=1`。

## 2. 主要文件

### `openclaw_evalscope_cli/`

新增的 EvalScope harness 包：

- `runner.py`
  - 注册 `@register_runner("openclaw-cli-harness")`
  - 实现 EvalScope `AgentRunner` 协议
  - 调用 `docker compose run openclaw-cli ...`
  - 每个样本前写入 OpenClaw provider 配置

- `cli.py`
  - 本地调试包装器
  - 调用 `openclaw agent --json`
  - 解析 OpenClaw JSON 输出文本

- `output.py`
  - 从 OpenClaw JSON 中抽取最终文本
  - 支持 `payloads[].text`、`result.payloads[].text`、`output_text`、Responses API 风格 `output[].content[].text`

- `run_evalscope.py`
  - 示例 EvalScope 入口
  - 构造 `ExternalAgentConfig(framework="openclaw-cli-harness")`
  - 默认 `mock_llm + gsm8k + limit=1`

- `docker-compose.evalscope.yml`
  - 定义 `openclaw-gateway` 常驻服务
  - 定义 `openclaw-cli` 一次性 CLI 服务
  - 共享 state/config volume
  - 配置 `host.docker.internal:host-gateway`

- `README.md`
  - 简要使用说明

### `openclaw-main/`

OpenClaw 源码目录。

本次修改过：

- `Dockerfile`
  - 配置 npm/pnpm registry mirror
  - `pnpm install` 加 `--config.minimumReleaseAge=0`
  - 保持 optional dependencies 启用，避免 native package lockfile 问题

- `DOCKERFILE_BUILD_NOTES.md`
  - Dockerfile 分阶段解释
  - 构建问题和修复记录

### 输出记录

- `outputs/openclaw_cli_harness_smoke/`
  - MockLLM 端到端 smoke

- `outputs/openclaw_cli_config_check/`
  - OpenClaw CLI target 参数、provider/model 切换检查

- `outputs/openclaw_real_aliyuncs_harness/`
  - AliyunCS 真实模型评测结果
  - `REAL_MODEL_REPORT.md`

## 3. OpenClaw 镜像构建

### 3.1 镜像 tag

baseline 镜像：

```text
openclaw-baseline:2026.6.11-srcsnap
```

后续修改源码后的实验镜像建议：

```text
openclaw-modified:<experiment-id>
```

baseline 和 modified 应使用同一 Dockerfile 构建方式，保证对比变量只来自源码差异。

### 3.2 Dockerfile 结构

`openclaw-main/Dockerfile` 是多阶段构建：

```text
workspace-deps
  -> build
  -> runtime-assets
  -> base-runtime
  -> final runtime
```

各阶段作用：

- `workspace-deps`
  - 只复制 workspace packages 和 extensions 的 `package.json`
  - 让 `pnpm install` 缓存尽量不受源码改动影响

- `bun-binary`
  - 从固定 digest 的 Bun 镜像复制 Bun binary
  - 避免构建时动态下载 Bun

- `build`
  - `corepack enable`
  - `pnpm install --frozen-lockfile`
  - 构建 OpenClaw server/CLI/UI
  - 构建可选扩展

- `runtime-assets`
  - `pnpm prune --prod`
  - 裁剪构建期文件、`.d.ts`、source map、未使用扩展

- final runtime
  - 基于 `node:24-bookworm-slim`
  - 安装运行时工具
  - 复制 `dist`、`node_modules`、模板、扩展、docs、skills
  - 创建 `/usr/local/bin/openclaw`
  - 切换到非 root `node`
  - 默认启动 `openclaw gateway`

### 3.3 本地 Dockerfile 关键构建修复

为适配当前网络和 pnpm 行为，`openclaw-main/Dockerfile` 中加入：

```dockerfile
RUN npm config set registry https://registry.npmmirror.com && \
    pnpm config set registry https://registry.npmmirror.com
```

依赖安装命令保持：

```dockerfile
RUN --mount=type=cache,id=openclaw-pnpm-store,target=/root/.local/share/pnpm/store,sharing=locked \
    NODE_OPTIONS=--max-old-space-size=2048 pnpm install --frozen-lockfile \
      --config.minimumReleaseAge=0 \
      --config.supportedArchitectures.os=linux \
      --config.supportedArchitectures.cpu="$(node -p 'process.arch')" \
      --config.supportedArchitectures.libc=glibc
```

说明：

- 保留 `--frozen-lockfile`，保证 baseline 可复现。
- 加 `--config.minimumReleaseAge=0`，避免 `pnpm-workspace.yaml` 里的 `minimumReleaseAge: 2880` 触发大量 registry metadata/attestation 请求。
- 不使用 `--no-optional`，因为 `@lydell/node-pty` 依靠 optional native packages 分发平台二进制包。

### 3.4 Docker daemon 代理

构建中遇到 Docker Hub base image 拉取超时。原因是 build args 只影响 Dockerfile 内部步骤，不影响 Docker daemon 拉取 base image metadata/layers。

修复方式是给 Docker daemon 配置代理：

```bash
sudo install -d /etc/systemd/system/docker.service.d

sudo tee /etc/systemd/system/docker.service.d/http-proxy.conf >/dev/null <<'EOF'
[Service]
Environment="HTTP_PROXY=socks5://172.20.64.1:7890"
Environment="HTTPS_PROXY=socks5://172.20.64.1:7890"
Environment="ALL_PROXY=socks5://172.20.64.1:7890"
Environment="NO_PROXY=localhost,127.0.0.1,::1"
EOF

sudo systemctl daemon-reload
sudo systemctl restart docker

systemctl show docker --property=Environment --no-pager
```

### 3.5 构建 baseline 镜像

```bash
cd /home/lenovo/code/AIE4902

PROXY_HOST="$(ip route show default | awk '{print $3}')"
export HTTP_PROXY="socks5://$PROXY_HOST:7890"
export HTTPS_PROXY="socks5://$PROXY_HOST:7890"
export ALL_PROXY="socks5://$PROXY_HOST:7890"
export NO_PROXY="localhost,127.0.0.1,::1"

docker build --progress=plain \
  --build-arg ALL_PROXY="$ALL_PROXY" \
  --build-arg HTTPS_PROXY="$HTTPS_PROXY" \
  --build-arg HTTP_PROXY="$HTTP_PROXY" \
  -t openclaw-baseline:2026.6.11-srcsnap \
  -f openclaw-main/Dockerfile \
  openclaw-main
```

验证：

```bash
docker image inspect openclaw-baseline:2026.6.11-srcsnap --format '{{.Id}} {{.Created}} {{.Size}}'
docker run --rm openclaw-baseline:2026.6.11-srcsnap openclaw --version
```

已验证镜像：

```text
openclaw-baseline:2026.6.11-srcsnap
OpenClaw 2026.6.11
```

### 3.6 构建 modified 镜像

修改源码后建议用单独 tag：

```bash
docker build --progress=plain \
  --build-arg ALL_PROXY="$ALL_PROXY" \
  --build-arg HTTPS_PROXY="$HTTPS_PROXY" \
  --build-arg HTTP_PROXY="$HTTP_PROXY" \
  -t openclaw-modified:<experiment-id> \
  -f openclaw-main/Dockerfile \
  openclaw-main
```

如果 modified 源码放在别的目录，则相应修改 `-f` 和 build context。

## 4. OpenClaw 服务启动

### 4.1 Compose 文件

使用：

```text
openclaw_evalscope_cli/docker-compose.evalscope.yml
```

服务：

- `openclaw-gateway`
  - 常驻 Gateway
  - 映射宿主端口 `OPENCLAW_GATEWAY_PORT -> 18789`
  - 默认命令：

```bash
openclaw gateway --allow-unconfigured --bind lan --port 18789
```

- `openclaw-cli`
  - 一次性 CLI service
  - `network_mode: service:openclaw-gateway`
  - 共享 Gateway 的网络、state/config volume
  - `entrypoint: ["openclaw"]`

共享目录：

- `OPENCLAW_EVAL_STATE_DIR -> /home/node/.openclaw`
- `OPENCLAW_EVAL_SECRET_DIR -> /home/node/.config/openclaw`

### 4.2 启动 baseline Gateway

```bash
cd /path/to/AIE4902

PROJECT_ROOT="$(pwd -P)"
export OPENCLAW_EVAL_STATE_DIR="$PROJECT_ROOT/openclaw_evalscope_cli/.openclaw-eval/state"
export OPENCLAW_EVAL_SECRET_DIR="$PROJECT_ROOT/openclaw_evalscope_cli/.openclaw-eval/secrets"

mkdir -p \
  "$OPENCLAW_EVAL_STATE_DIR" \
  "$OPENCLAW_EVAL_SECRET_DIR"

export OPENCLAW_IMAGE=openclaw-baseline:2026.6.11-srcsnap
export OPENCLAW_COMPOSE_PROJECT=openclaw-eval-baseline
export OPENCLAW_GATEWAY_PORT=18789

docker compose \
  -f openclaw_evalscope_cli/docker-compose.evalscope.yml \
  -p "$OPENCLAW_COMPOSE_PROJECT" \
  up -d openclaw-gateway
```

查看状态：

```bash
docker compose \
  -f openclaw_evalscope_cli/docker-compose.evalscope.yml \
  -p openclaw-eval-baseline \
  ps
```

健康检查：

```bash
curl -fsS http://127.0.0.1:18789/healthz
```

已验证返回：

```json
{"ok":true,"status":"live"}
```

### 4.3 CLI 版本检查

```bash
docker compose \
  -f openclaw_evalscope_cli/docker-compose.evalscope.yml \
  -p openclaw-eval-baseline \
  run --rm --no-deps -T openclaw-cli --version
```

已验证：

```text
OpenClaw 2026.6.11
```

### 4.4 modified Gateway 启动建议

modified 和 baseline 必须隔离：

```bash
PROJECT_ROOT="$(pwd -P)"

export OPENCLAW_IMAGE=openclaw-modified:<experiment-id>
export OPENCLAW_COMPOSE_PROJECT=openclaw-eval-modified
export OPENCLAW_GATEWAY_PORT=18790
export OPENCLAW_EVAL_STATE_DIR="$PROJECT_ROOT/openclaw_evalscope_cli/.openclaw-eval/modified/state"
export OPENCLAW_EVAL_SECRET_DIR="$PROJECT_ROOT/openclaw_evalscope_cli/.openclaw-eval/modified/secrets"

mkdir -p "$OPENCLAW_EVAL_STATE_DIR" "$OPENCLAW_EVAL_SECRET_DIR"

docker compose \
  -f openclaw_evalscope_cli/docker-compose.evalscope.yml \
  -p "$OPENCLAW_COMPOSE_PROJECT" \
  up -d openclaw-gateway
```

## 5. EvalScope 接入方式

### 5.1 runner 注册

`openclaw_evalscope_cli/runner.py` 注册：

```python
@register_runner("openclaw-cli-harness")
class OpenClawCliHarnessRunner(AgentRunner):
    ...
```

EvalScope 使用：

```python
agent_config = {
    "mode": "external",
    "framework": "openclaw-cli-harness",
    "environment": "local",
    "timeout": 600,
    "kwargs": {
        "compose_project": "openclaw-eval-baseline",
        "gateway_service": "openclaw-gateway",
        "cli_service": "openclaw-cli",
        "agent_id": "main",
        "protocol": "responses",
    },
}
```

### 5.2 runner 的每样本流程

`setup()`：

1. 检查 `docker compose version`
2. `docker compose up -d openclaw-gateway`
3. 等待 Gateway `/healthz`
4. 检查 `openclaw --version`

`run()`：

1. 读取 EvalScope bridge endpoint
2. 写入 OpenClaw provider：

```text
models.providers.evalscope.baseUrl = <bridge>/openai/v1
models.providers.evalscope.apiKey  = <trial token>
models.providers.evalscope.api     = openai-responses
models.providers.evalscope.models  = [{"id": "<model_name>", "name": "<model_name>"}]
```

3. 合并 agent 默认模型 allowlist：

```text
agents.defaults.models += {"evalscope/<model_name>": {}}
```

4. 调用：

```bash
openclaw agent \
  --agent main \
  --session-key agent:main:evalscope-<sample-id> \
  --model evalscope/<model_name> \
  --message-file <prompt-file> \
  --json \
  --timeout <seconds>
```

5. 从 OpenClaw JSON 输出中抽取最终答案。

### 5.3 关于 `--model evalscope/<model_name>`

OpenClaw 不能凭空调用 `evalscope/<model_name>`。

它需要：

1. `models.providers.evalscope` 中存在该模型。
2. `agents.defaults.models` 允许 `evalscope/<model_name>`。
3. `models.providers.evalscope.baseUrl` 指向当前仍在运行的 EvalScope bridge。
4. `apiKey` 是当前 EvalScope trial token。

正式 EvalScope harness 中，这些配置由 runner 自动写入。手工直接运行 `openclaw agent --model evalscope/deepseek-v3.2` 只有在 EvalScope bridge 正在运行且 token 仍有效时才会成功。

### 5.4 为什么裸 `openclaw agent --message ...` 会失败

曾复现：

```bash
docker exec openclaw-eval-baseline-openclaw-gateway-1 \
  openclaw agent --message "who are u"
```

报错：

```text
Error: No target session selected. Use --agent <id>, --session-key <key>, --session-id <id>, or --to <E.164>.
```

原因：OpenClaw CLI 需要目标会话。正确形态必须带：

```bash
--agent main --session-key agent:main:<some-key>
```

## 6. 使用 EvalScope 评测

### 6.1 激活虚拟环境

```bash
source /home/lenovo/code/AIE4902/.venv/bin/activate
```

### 6.2 MockLLM smoke

用于验证完整 harness 链路，不消耗真实模型额度：

```bash
cd /path/to/AIE4902

PROJECT_ROOT="$(pwd -P)"

export OPENCLAW_IMAGE=openclaw-baseline:2026.6.11-srcsnap
export OPENCLAW_COMPOSE_PROJECT=openclaw-eval-baseline
export OPENCLAW_GATEWAY_PORT=18789
export OPENCLAW_EVAL_STATE_DIR="$PROJECT_ROOT/openclaw_evalscope_cli/.openclaw-eval/state"
export OPENCLAW_EVAL_SECRET_DIR="$PROJECT_ROOT/openclaw_evalscope_cli/.openclaw-eval/secrets"

export EVALSCOPE_DATASET=gsm8k
export EVALSCOPE_LIMIT=1
export EVALSCOPE_EVAL_TYPE=mock_llm
export EVALSCOPE_MODEL=mock
export EVALSCOPE_WORK_DIR=outputs/openclaw_cli_harness_smoke

python -m openclaw_evalscope_cli.run_evalscope
```

已验证链路：

```text
EvalScope -> openclaw-cli-harness -> openclaw agent --json -> Gateway -> EvalScope bridge -> MockLLM
```

生成报告示例：

```text
outputs/openclaw_cli_harness_smoke/20260708_155933/reports/openclaw_cli_harness/gsm8k.json
outputs/openclaw_cli_harness_smoke/20260708_155933/reports/report.html
```

### 6.3 真实 AliyunCS 模型 smoke

AliyunCS 配置来自本项目已有 `aliyuncs/` 包：

- 默认模型：`deepseek-v3.2`
- base URL：`https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1`
- API key：通过 `ALIYUNCS_API_KEY` 或 `aliyuncs.get_api_key()` 获取

运行：

```bash
source /home/lenovo/code/AIE4902/.venv/bin/activate

python - <<'PY'
import os
from pathlib import Path

from aliyuncs import ALIYUNCS_BASE_URL, get_api_key, get_model_name
from openclaw_evalscope_cli.run_evalscope import main

root = Path.cwd().resolve()
os.environ.update({
    'OPENCLAW_IMAGE': 'openclaw-baseline:2026.6.11-srcsnap',
    'OPENCLAW_COMPOSE_PROJECT': 'openclaw-eval-baseline',
    'OPENCLAW_EVAL_STATE_DIR': str(root / 'openclaw_evalscope_cli/.openclaw-eval/state'),
    'OPENCLAW_EVAL_SECRET_DIR': str(root / 'openclaw_evalscope_cli/.openclaw-eval/secrets'),
    'OPENCLAW_GATEWAY_PORT': '18789',
    'EVALSCOPE_DATASET': 'gsm8k',
    'EVALSCOPE_LIMIT': '1',
    'EVALSCOPE_FEW_SHOT_NUM': '0',
    'EVALSCOPE_MODEL': get_model_name(),
    'EVALSCOPE_MODEL_ID': 'openclaw_aliyuncs_real_smoke',
    'EVALSCOPE_EVAL_TYPE': 'openai_api',
    'EVALSCOPE_API_URL': ALIYUNCS_BASE_URL,
    'EVALSCOPE_API_KEY': get_api_key(),
    'EVALSCOPE_TEMPERATURE': '0.0',
    'EVALSCOPE_MAX_TOKENS': '512',
    'EVALSCOPE_AGENT_TIMEOUT': '600',
    'EVALSCOPE_WORK_DIR': 'outputs/openclaw_real_aliyuncs_harness',
    'EVALSCOPE_JUDGE_STRATEGY': 'rule',
})
main()
PY
```

已验证结果：

```text
Model:   openclaw_aliyuncs_real_smoke
Dataset: gsm8k
Subset:  main
Num:     1
Metric:  mean_acc
Score:   1.0
```

报告：

```text
outputs/openclaw_real_aliyuncs_harness/REAL_MODEL_REPORT.md
outputs/openclaw_real_aliyuncs_harness/20260708_192356/reports/openclaw_aliyuncs_real_smoke/gsm8k.json
outputs/openclaw_real_aliyuncs_harness/20260708_192356/reports/report.html
outputs/openclaw_real_aliyuncs_harness/20260708_192356/predictions/openclaw_aliyuncs_real_smoke/gsm8k_main.jsonl
```

关键日志：

```text
openclaw-cli-harness launching: sample=0 model=evalscope/deepseek-v3.2
bridge[openclaw-cli-harness/4bd635b4] step=0 stream latency=5.32s tokens=21721+168 stop='stop'
openclaw-cli-harness exited: sample=0 rc=0 wall=10.8s stdout=21504B stderr=0B timed_out=False
```

### 6.4 正式小样本 baseline

建议先跑 `limit=5`：

```bash
source /home/lenovo/code/AIE4902/.venv/bin/activate

PROJECT_ROOT="$(pwd -P)"

export OPENCLAW_IMAGE=openclaw-baseline:2026.6.11-srcsnap
export OPENCLAW_COMPOSE_PROJECT=openclaw-eval-baseline
export OPENCLAW_GATEWAY_PORT=18789
export OPENCLAW_EVAL_STATE_DIR="$PROJECT_ROOT/openclaw_evalscope_cli/.openclaw-eval/state"
export OPENCLAW_EVAL_SECRET_DIR="$PROJECT_ROOT/openclaw_evalscope_cli/.openclaw-eval/secrets"

export EVALSCOPE_DATASET=gsm8k
export EVALSCOPE_LIMIT=5
export EVALSCOPE_FEW_SHOT_NUM=0
export EVALSCOPE_MODEL=deepseek-v3.2
export EVALSCOPE_MODEL_ID=openclaw_baseline_deepseek_v32
export EVALSCOPE_EVAL_TYPE=openai_api
export EVALSCOPE_API_URL=https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1
export EVALSCOPE_API_KEY="$ALIYUNCS_API_KEY"
export EVALSCOPE_TEMPERATURE=0.0
export EVALSCOPE_MAX_TOKENS=512
export EVALSCOPE_WORK_DIR=outputs/openclaw/baseline

python -m openclaw_evalscope_cli.run_evalscope
```

注意：不要把真实 API key 写入文档或源码。优先从环境变量或 `.env` 读取。

### 6.5 正式小样本 modified

```bash
source /home/lenovo/code/AIE4902/.venv/bin/activate

PROJECT_ROOT="$(pwd -P)"

export OPENCLAW_IMAGE=openclaw-modified:<experiment-id>
export OPENCLAW_COMPOSE_PROJECT=openclaw-eval-modified
export OPENCLAW_GATEWAY_PORT=18790
export OPENCLAW_EVAL_STATE_DIR="$PROJECT_ROOT/openclaw_evalscope_cli/.openclaw-eval/modified/state"
export OPENCLAW_EVAL_SECRET_DIR="$PROJECT_ROOT/openclaw_evalscope_cli/.openclaw-eval/modified/secrets"

export EVALSCOPE_DATASET=gsm8k
export EVALSCOPE_LIMIT=5
export EVALSCOPE_FEW_SHOT_NUM=0
export EVALSCOPE_MODEL=deepseek-v3.2
export EVALSCOPE_MODEL_ID=openclaw_modified_deepseek_v32
export EVALSCOPE_EVAL_TYPE=openai_api
export EVALSCOPE_API_URL=https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1
export EVALSCOPE_API_KEY="$ALIYUNCS_API_KEY"
export EVALSCOPE_TEMPERATURE=0.0
export EVALSCOPE_MAX_TOKENS=512
export EVALSCOPE_WORK_DIR=outputs/openclaw/modified

python -m openclaw_evalscope_cli.run_evalscope
```

## 7. 对比报告

EvalScope 输出通常在：

```text
<work_dir>/<timestamp>/reports/*.json
<work_dir>/<timestamp>/reports/report.html
```

baseline 和 modified 对比时关注：

- `score`
- `metrics[].score`
- `num`
- `predictions/*.jsonl`
- `reviews/*.jsonl`
- `logs/eval_log.log`

也可以启动 EvalScope dashboard：

```bash
source /home/lenovo/code/AIE4902/.venv/bin/activate
evalscope service --host 0.0.0.0 --port 9000 --outputs outputs
```

## 8. 已验证项目状态

### 镜像

```text
openclaw-baseline:2026.6.11-srcsnap
OpenClaw 2026.6.11
```

### Gateway

```text
openclaw-eval-baseline-openclaw-gateway-1
STATUS: healthy
PORT: 18789
```

### MockLLM smoke

```text
EvalScope -> runner -> OpenClaw CLI -> Gateway -> EvalScope bridge -> MockLLM
通过
```

### 模型切换检查

使用：

```text
EVALSCOPE_MODEL=mock-switch-check
```

runner 日志显示：

```text
openclaw-cli-harness launching: sample=0 model=evalscope/mock-switch-check
```

OpenClaw provider 被写入：

```json
{
  "models": [
    {
      "id": "mock-switch-check",
      "name": "mock-switch-check"
    }
  ]
}
```

### 真实模型 smoke

```text
Model: deepseek-v3.2
Dataset: gsm8k
Limit: 1
Score: 1.0
```

## 9. 常见问题

### Docker build 拉镜像慢或超时

build args 不影响 daemon 拉 base image。需要配置 Docker daemon proxy。

### pnpm registry 请求很多且很慢

`minimumReleaseAge` 会触发额外 metadata/attestation 请求。构建时用：

```bash
--config.minimumReleaseAge=0
```

### 不要加 `--no-optional`

OpenClaw 依赖 `@lydell/node-pty` 的 optional native packages。禁用 optional 会导致 lockfile/native package 问题。

### 不建议 `pnpm install --no-frozen-lockfile`

baseline 需要可复现。不要为了绕过 lockfile 报错而改依赖图。

### 手工 `openclaw agent --message` 报 No target session

必须指定：

```bash
--agent main --session-key agent:main:<key>
```

### 手工 `openclaw agent --model evalscope/...` 报 network error

如果 EvalScope bridge 已退出，OpenClaw provider 里保存的 `host.docker.internal:<port>` 会失效。正式评测时 runner 会为每个样本重写有效 bridge URL 和 token。

## 10. 参考文件

- `openclaw_evalscope_cli/README.md`
- `openclaw_evalscope_cli/runner.py`
- `openclaw_evalscope_cli/run_evalscope.py`
- `openclaw_evalscope_cli/docker-compose.evalscope.yml`
- `openclaw-main/DOCKERFILE_BUILD_NOTES.md`
- `outputs/openclaw_cli_config_check/README.md`
- `outputs/openclaw_real_aliyuncs_harness/REAL_MODEL_REPORT.md`

## 11. Agent Benchmark 验证：非 Harbor 路线

更新时间：2026-07-10

### 11.1 数据集选择

原目标示例是 Terminal-Bench-2.1 前两个任务，但 EvalScope 的 `terminal_bench_v2_1` 依赖 Terminal-Bench/Harbor 运行环境。当前要求是“选取其他不依赖 harbor”，因此改用 EvalScope 内置的 `browsecomp`：

```text
Dataset: browsecomp
Tags: Agent, Knowledge, QA
Adapter: AgentAdapter
External agent_config: supported
Harbor: not required
```

`browsecomp` 是搜索型 agent benchmark，可以通过 `TaskConfig.agent_config` 走 external agent runner，因此适合验证：

```text
EvalScope -> openclaw-cli-harness runner -> openclaw agent --json -> Gateway -> EvalScope bridge -> upstream model
```

### 11.2 已观察到的有效链路证据

第一次 `browsecomp limit=2` 运行目录：

```text
outputs/openclaw_browsecomp_limit2/20260709_235525/
```

关键证据：

- `logs/eval_log.log` 显示 dataset 成功加载，EvalScope bridge 启动。
- `logs/eval_log.log` 显示 `openclaw-cli-harness launching: sample=0 model=evalscope/deepseek-v3.2`。
- `logs/eval_log.log` 显示 bridge 记录了 sample 0 的 17 个模型/tool step，最后 `stop='stop'`。
- `logs/eval_log.log` 显示 `openclaw-cli-harness exited: sample=0 rc=0`。
- `predictions/openclaw_browsecomp_real_limit2/browsecomp_default.jsonl` 已生成 1 条预测。

这证明 OpenClaw CLI harness 评测主链路是可执行的。

### 11.3 暴露的问题：workspace 清理过于激进

第一次验证时，为了检查“新 task 前是否清理 workspace”，runner 在样本前清理了 workspace 根目录，只保留 `.git`：

```text
openclaw-cli-harness workspace cleanup: sample=0 path=/home/node/.openclaw/workspace before=10 after=1 preserve_git=True
```

这会删除 OpenClaw 自己的 workspace seed/context 文件：

```text
AGENTS.md
SOUL.md
TOOLS.md
IDENTITY.md
USER.md
HEARTBEAT.md
openclaw-workspace-state.json
```

OpenClaw 对 workspace 有 attestation 保护。被 attested 的 workspace 如果被擦空，后续启动会拒绝自动重新 seed，报错：

```text
WorkspaceVanishedError:
OpenClaw workspace appears to have disappeared after a recent initialization.
Refusing to reseed BOOTSTRAP.md over a recently attested workspace.
```

结论：不能把 OpenClaw workspace 根 seed 文件视为评测脏状态。

### 11.4 已修复的清理策略

`openclaw_evalscope_cli/runner.py` 已改为 allowlist 清理：

默认保留：

```text
.git
.agents
skills
memory
AGENTS.md
SOUL.md
TOOLS.md
IDENTITY.md
USER.md
HEARTBEAT.md
BOOTSTRAP.md
MEMORY.md
openclaw-workspace-state.json
```

只删除不在 allowlist 中的评测残留文件，例如手工放入的 marker、任务生成的临时文件等。

新日志格式：

```text
openclaw-cli-harness workspace cleanup: sample=<id> path=<workspace> before=<n> after=<n> removed=<n> preserved=<n>
```

runner 也会把清理结果写进 `AgentRunResult.metrics.workspace_cleanup`：

```json
{
  "enabled": true,
  "workspace": "/home/node/.openclaw/workspace",
  "entries_before": 9,
  "entries_after": 8,
  "removed_count": 1,
  "removed_entries": ["__stale_marker_before_browsecomp.txt"],
  "preserved_entries": ["AGENTS.md", "..."]
}
```

`openclaw_evalscope_cli/run_evalscope.py` 新增环境变量：

```bash
export OPENCLAW_CLEAN_WORKSPACE=true
export OPENCLAW_WORKSPACE_PATH=/home/node/.openclaw/workspace
export OPENCLAW_PRESERVE_WORKSPACE_GIT=true
export OPENCLAW_WORKSPACE_PRESERVE_EXTRA_ENTRIES="my-required-file"
```

多个 extra entries 用 `:` 分隔。

### 11.5 当前 state 恢复

由于旧清理已经把当前 baseline bind mount 的 workspace seed 文件删除，已从 `openclaw-main/docs/reference/templates/` 恢复到：

```text
openclaw_evalscope_cli/.openclaw-eval/state/workspace/
```

当前已恢复：

```text
.git
AGENTS.md
HEARTBEAT.md
IDENTITY.md
SOUL.md
TOOLS.md
USER.md
openclaw-workspace-state.json
```

### 11.6 推荐重跑命令

受当前执行环境限制，Codex 会话无法访问 Docker socket；下面命令需要在你的 shell 中运行。

先放入一个 marker，用于验证样本前清理会删除评测残留，但保留 OpenClaw seed 文件：

```bash
docker exec openclaw-eval-baseline-openclaw-gateway-1 sh -lc '
  mkdir -p "$OPENCLAW_WORKSPACE_DIR"
  echo stale > "$OPENCLAW_WORKSPACE_DIR/__stale_marker_before_browsecomp.txt"
  find "$OPENCLAW_WORKSPACE_DIR" -mindepth 1 -maxdepth 1 -printf "%f\n" | sort
'
```

然后运行 `browsecomp` 前两个样本：

```bash
cd /home/lenovo/code/AIE4902
source /home/lenovo/code/AIE4902/.venv/bin/activate

python - <<'PY'
import os
from pathlib import Path

from aliyuncs import ALIYUNCS_BASE_URL, get_api_key, get_model_name

root = Path.cwd().resolve()
os.environ.update({
    'OPENCLAW_IMAGE': 'openclaw-baseline:2026.6.11-srcsnap',
    'OPENCLAW_COMPOSE_PROJECT': 'openclaw-eval-baseline',
    'OPENCLAW_GATEWAY_PORT': '18789',
    'OPENCLAW_EVAL_STATE_DIR': str(root / 'openclaw_evalscope_cli/.openclaw-eval/state'),
    'OPENCLAW_EVAL_SECRET_DIR': str(root / 'openclaw_evalscope_cli/.openclaw-eval/secrets'),
    'OPENCLAW_CLEAN_WORKSPACE': 'true',
    'OPENCLAW_PRESERVE_WORKSPACE_GIT': 'true',
    'EVALSCOPE_DATASET': 'browsecomp',
    'EVALSCOPE_LIMIT': '2',
    'EVALSCOPE_MODEL': get_model_name(),
    'EVALSCOPE_MODEL_ID': 'openclaw_browsecomp_real_limit2',
    'EVALSCOPE_EVAL_TYPE': 'openai_api',
    'EVALSCOPE_API_URL': ALIYUNCS_BASE_URL,
    'EVALSCOPE_API_KEY': get_api_key(),
    'EVALSCOPE_FEW_SHOT_NUM': '0',
    'EVALSCOPE_TEMPERATURE': '0.0',
    'EVALSCOPE_MAX_TOKENS': '2048',
    'EVALSCOPE_AGENT_TIMEOUT': '900',
    'EVALSCOPE_WORK_DIR': str(root / 'outputs/openclaw_browsecomp_limit2'),
    'EVALSCOPE_JUDGE_STRATEGY': 'auto',
})

from openclaw_evalscope_cli.run_evalscope import main
main()
PY
```

重跑后检查日志：

```bash
latest="$(ls -dt outputs/openclaw_browsecomp_limit2/* | head -1)"
grep -E "workspace cleanup|launching: sample=|exited: sample=|bridge\\[openclaw-cli-harness" "$latest/logs/eval_log.log"
wc -l "$latest/predictions/openclaw_browsecomp_real_limit2/browsecomp_default.jsonl"
```

期望：

- 日志里出现新格式 `removed=<n> preserved=<n>`。
- 第一个样本前 `removed_entries` 或日志计数能体现 marker 被删除。
- 两个样本都出现 `launching` 和 `exited rc=0`。
- prediction JSONL 行数为 `2`。

## 12. EvalScope 数据集下载位置与修改方式

### 12.1 默认下载位置

当前 EvalScope 源码中的默认数据集缓存目录由
`evalscope/evalscope/constants.py` 的 `DEFAULT_DATASET_CACHE_DIR` 定义：

```text
~/.cache/modelscope/hub/datasets
```

在当前用户 `lenovo` 下，对应实际路径：

```text
/home/lenovo/.cache/modelscope/hub/datasets
```

首次运行某个 benchmark 时，EvalScope 会通过配置的 dataset hub 下载数据并缓存到该目录。后续运行通常会复用缓存。

可以用下面的命令查看当前缓存：

```bash
du -sh /home/lenovo/.cache/modelscope/hub/datasets
find /home/lenovo/.cache/modelscope/hub/datasets -mindepth 1 -maxdepth 2 -type d | sort | head -50
```

### 12.2 使用 EvalScope CLI 修改目录

直接使用 EvalScope CLI 时，通过 `--dataset-dir` 指定数据集目录，通过 `--dataset-hub` 指定下载源：

```bash
source /home/lenovo/code/AIE4902/.venv/bin/activate

evalscope eval \
  --model mock \
  --eval-type mock_llm \
  --datasets gsm8k \
  --limit 5 \
  --dataset-dir /data/evalscope/datasets \
  --dataset-hub modelscope
```

如果使用 Hugging Face 数据源，可把 `--dataset-hub` 改为当前 EvalScope 版本支持的 Hugging Face hub 名称。可通过以下命令确认参数选项：

```bash
evalscope eval --help | grep -A 3 -E "dataset-dir|dataset-hub"
```

### 12.3 使用 Python 配置修改目录

调用 `run_task()` 时可直接设置：

```python
from evalscope import run_task

run_task({
    "model": "mock",
    "eval_type": "mock_llm",
    "datasets": ["gsm8k"],
    "limit": 5,
    "dataset_dir": "/data/evalscope/datasets",
    "dataset_hub": "modelscope",
})
```

### 12.4 OpenClaw harness 中修改目录

本项目的 `openclaw_evalscope_cli/run_evalscope.py` 已读取以下环境变量：

```bash
export EVALSCOPE_DATASET_DIR=/data/evalscope/datasets
export EVALSCOPE_DATASET_HUB=modelscope
```

完整运行示例：

```bash
cd /home/lenovo/code/AIE4902
source /home/lenovo/code/AIE4902/.venv/bin/activate

export EVALSCOPE_DATASET=browsecomp
export EVALSCOPE_LIMIT=2
export EVALSCOPE_DATASET_DIR=/data/evalscope/datasets
export EVALSCOPE_DATASET_HUB=modelscope
export EVALSCOPE_WORK_DIR=/data/evalscope/outputs/openclaw-browsecomp

python -m openclaw_evalscope_cli.run_evalscope
```

baseline 和 modified 对比实验应使用相同的 `EVALSCOPE_DATASET_DIR`，保证两组评测读取同一份数据集版本和缓存。

### 12.5 三类目录不要混淆

| 配置 | 用途 | 示例 |
|---|---|---|
| `EVALSCOPE_DATASET_DIR` | benchmark 数据集下载和缓存 | `/data/evalscope/datasets` |
| `EVALSCOPE_WORK_DIR` | EvalScope 日志、预测和报告 | `/data/evalscope/outputs/openclaw-browsecomp` |
| `OPENCLAW_EVAL_STATE_DIR` | OpenClaw config、session、workspace 等运行状态 | `openclaw_evalscope_cli/.openclaw-eval/state` |

不要把数据集目录放进 `OPENCLAW_EVAL_STATE_DIR`。后者是容器运行状态，可能在重建实验环境时被清理，也可能包含 token、session 和 OpenClaw 自动生成的嵌套 workspace 仓库。

### 12.6 迁移已有缓存

如果服务器已经下载过数据集，可以直接复制缓存，再把 `EVALSCOPE_DATASET_DIR` 指向新位置：

```bash
sudo mkdir -p /data/evalscope/datasets
sudo rsync -a --info=progress2 \
  /home/lenovo/.cache/modelscope/hub/datasets/ \
  /data/evalscope/datasets/
sudo chown -R lenovo:lenovo /data/evalscope/datasets
```

复制完成后先用小样本验证：

```bash
export EVALSCOPE_DATASET_DIR=/data/evalscope/datasets
export EVALSCOPE_DATASET_HUB=modelscope
export EVALSCOPE_DATASET=gsm8k
export EVALSCOPE_LIMIT=1
export EVALSCOPE_MODEL=mock
export EVALSCOPE_EVAL_TYPE=mock_llm

python -m openclaw_evalscope_cli.run_evalscope
```

## 13. LLM Judge、自定义评分指标与 Token 指标

### 13.1 EvalScope 什么时候调用 LLM Judge

Judge 的主配置在 `TaskConfig.judge_strategy` 和 `TaskConfig.judge_model_args`：

| `judge_strategy` | 行为 |
|---|---|
| `rule` | 只使用规则指标，不调用 Judge 模型 |
| `llm` | 每个样本都使用 Judge 模型评分 |
| `llm_recall` | 先做规则评分，规则结果未达到满分时再调用 Judge |
| `auto` | 由 benchmark adapter 决定；例如 BrowseComp 默认启用 LLM Judge |

`analysis_report=true` 是另一条独立的 LLM 调用路径：它使用 Judge 模型生成报告分析，即使评分策略是 `rule` 也可能产生模型调用。

本项目的 OpenClaw 入口默认使用 `auto`。未提供单独 Judge 配置时，会复用当前被评测模型的 model、API URL、API key 和 eval type：

```bash
export EVALSCOPE_JUDGE_STRATEGY=auto
```

需要使用独立 Judge 模型时，可以按字段配置：

```bash
export EVALSCOPE_JUDGE_MODEL=deepseek-v3.2
export EVALSCOPE_JUDGE_EVAL_TYPE=openai_api
export EVALSCOPE_JUDGE_API_URL="$EVALSCOPE_API_URL"
export EVALSCOPE_JUDGE_API_KEY="$EVALSCOPE_API_KEY"
export EVALSCOPE_JUDGE_TEMPERATURE=0.0
export EVALSCOPE_JUDGE_MAX_TOKENS=4096
```

也可以一次传入完整 JSON。注意 Judge 模型字段名是 `model_id`，不是 `model`：

```bash
export EVALSCOPE_JUDGE_MODEL_ARGS='{
  "model_id": "deepseek-v3.2",
  "eval_type": "openai_api",
  "api_url": "https://example.com/v1/chat/completions",
  "api_key": "...",
  "generation_config": {"temperature": 0.0, "max_tokens": 4096}
}'
```

API key 应通过环境变量或 `.env` 提供，不要写入源码、README 或镜像层。

### 13.2 自定义评分指标

普通评分指标作用于单个样本的 `prediction` 和 `reference`，通过 `@register_metric` 注册：

```python
from evalscope.api.metric import Metric
from evalscope.api.registry import register_metric


@register_metric("answer_length_ratio")
class AnswerLengthRatio(Metric):
    def apply(self, predictions: list[str], references: list[str]) -> list[float]:
        scores = []
        for prediction, reference in zip(predictions, references):
            denominator = max(1, len(reference))
            scores.append(min(1.0, len(prediction) / denominator))
        return scores
```

注册模块必须在创建 benchmark 之前被导入，并由自定义 benchmark 的 `metric_list` 引用 `answer_length_ratio`。这类 metric 用于答案质量，不适合统计 token、延迟等运行数据，因为 `Metric.apply()` 不接收 `TaskState` 或模型 usage。

### 13.3 任务级 Token 指标

项目中的 token 指标通过 EvalScope performance collector 采集，不计入 LLM Judge 和 `analysis_report` 的消耗。

对 OpenClaw CLI harness，一个 benchmark 样本可能包含多次模型调用。EvalScope 会先把该样本所有 bridge 调用的 input/output token 求和，得到任务级用量，再在数据集级汇总：

```text
Total Tok
Avg Tok/Task
Min Tok/Task
Max Tok/Task
```

结果位置：

- 每任务：`predictions/...jsonl` 的 `model_output.metadata.task_usage`。
- 数据集汇总：`reports/<model>/<dataset>.json` 的 `perf_metrics.summary.task_usage`。
- 展示：单数据集控制台表、Overall report table 和 `report.html`。

JSON 中同时保留 input/output/total 的详细统计，控制台和 HTML 只显示上述四个紧凑列。provider 未返回 usage 或使用不含 usage 的旧缓存时显示 `-`，不会错误记为 0。

可以关闭采集：

```bash
export EVALSCOPE_COLLECT_PERF=false
```

### 13.4 EvalScope fork 与依赖锁定

任务级 token 指标实现在 EvalScope fork 的以下分支和提交中：

```text
Repository: https://github.com/Asuna-L/evalscope
Branch: feature/task-token-metrics
Commit: cd25a08ec54bde5b4b895d43324a022e54c958b1
```

根目录 `requirements.txt` 已锁定该 commit。推送本地分支后，服务器执行以下命令即可安装相同版本：

```bash
python -m pip install -r requirements.txt
```

### 13.5 使用 `run.py` 验证新指标

根目录 `run.py` 是当前 OpenClaw EvalScope 测试入口，默认配置为：

- baseline 镜像 `openclaw-baseline:2026.6.11-srcsnap`
- `gsm8k --limit 1`
- `judge_strategy=auto`，Judge 默认复用被评测模型
- `collect_perf=true`，生成任务级 token 和数据集汇总列
- 输出到 `outputs/<model_id>__<dataset>/<timestamp>/`

运行前确保 `.env` 或环境变量中存在 `ALIYUNCS_API_KEY`：

```bash
cd /path/to/AIE4902
source .venv/bin/activate
python run.py
```

脚本使用 `setdefault` 设置测试默认值，所以可以从 shell 覆盖模型、数据集、limit、Judge 或镜像，无需修改文件。例如：

```bash
export OPENCLAW_IMAGE=openclaw-modified:<experiment-id>
export OPENCLAW_COMPOSE_PROJECT=openclaw-eval-modified
export OPENCLAW_GATEWAY_PORT=18790
export EVALSCOPE_MODEL_ID=openclaw_modified_deepseek_v32
export EVALSCOPE_LIMIT=5

python run.py
```

常用的结构化覆盖变量：

| 环境变量 | 格式 | 用途 |
|---|---|---|
| `EVALSCOPE_DATASETS` | 逗号分隔或 JSON list | 一次评测多个数据集 |
| `EVALSCOPE_DATASET_ARGS` | JSON object | subset、few-shot、dataset id 等数据集参数 |
| `EVALSCOPE_GENERATION_CONFIG` | JSON object | 覆盖任意生成参数 |
| `EVALSCOPE_AGENT_CONFIG` | JSON object | 覆盖 external agent/bridge/runner 配置 |
| `EVALSCOPE_JUDGE_MODEL_ARGS` | JSON object | 完整 Judge 模型配置 |
| `EVALSCOPE_TASK_CONFIG` | JSON object | 最后应用的完整 TaskConfig 深度覆盖，优先级最高 |

例如，MMLU 默认有 57 个 subset，`limit=2` 会产生 `57 * 2 = 114` 个任务。只测试两个学科可以配置：

```bash
export EVALSCOPE_DATASET=mmlu
export EVALSCOPE_LIMIT=2
export EVALSCOPE_DATASET_ARGS='{
  "mmlu": {
    "subset_list": ["abstract_algebra", "anatomy"],
    "few_shot_num": 0
  }
}'

python run.py
```

未单独映射的 EvalScope 参数也可以通过最高优先级配置覆盖：

```bash
export EVALSCOPE_TASK_CONFIG='{
  "eval_batch_size": 1,
  "generation_config": {"top_p": 0.9},
  "judge_strategy": "rule"
}'
```

OpenClaw harness v1 会为每个样本更新共享 provider/token，因此 `EVALSCOPE_BATCH_SIZE` 默认并建议保持为 `1`。

默认情况下，输出目录使用最终生效的模型 ID 和数据集名称。例如：

```text
outputs/openclaw_deepseek-v3.2__gsm8k/20260712_093913/
```

- `EVALSCOPE_OUTPUT_ROOT` 修改输出根目录，同时保留自动生成的模型/数据集目录。
- `EVALSCOPE_WORK_DIR` 直接指定完整工作目录，并关闭自动的模型/数据集目录命名。
- EvalScope 默认继续在工作目录下追加时间戳；只有显式设置 `EVALSCOPE_NO_TIMESTAMP=true` 才会取消。

## 14. 五类非 Harbor Benchmark

以下数据集均由 EvalScope 直接从 ModelScope 下载，不依赖 Harbor benchmark 镜像。评测入口仍然是：

```text
EvalScope -> openclaw-cli-harness -> openclaw agent --json -> OpenClaw Gateway -> EvalScope bridge -> model
```

运行前先启动虚拟环境，并确保 OpenClaw baseline 或 modified 镜像已经构建完成：

```bash
cd /path/to/AIE4902
source .venv/bin/activate
```

模型、API 地址和 API key 继续从 `.env` 或 `EVALSCOPE_MODEL`、`EVALSCOPE_API_URL`、
`EVALSCOPE_API_KEY` 读取。建议为同一组 baseline/modified 实验固定相同的模型、seed、生成参数和
Judge 配置，只切换 `OPENCLAW_IMAGE`、`OPENCLAW_COMPOSE_PROJECT` 与 Gateway 端口。

### 14.1 数据集选择

| 能力 | 原始要求 | 本项目采用的 EvalScope 数据集 | 主要指标 | 选择说明 |
|---|---|---|---|---|
| 基础知识 | MMLU-Pro | `mmlu_pro` | `acc` | 原生 MMLU-Pro，包含 14 个学科 |
| 复杂推理 | GPQA | `gpqa_diamond` | `acc` | GPQA Diamond，包含 198 道高难度理工科问题 |
| 多轮对话 | Lost in Conversation | `longmemeval` | `acc` | EvalScope 当前没有 LiC adapter，使用长对话历史中的意图、事实和时间信息检索作为近似 |
| 多步工具使用 | ToolBench | `acebench` 的 `agent` 子集 | `acc`、`process_acc`、`end_state_acc` | API schema 会写入文本 prompt，能够通过 OpenClaw external CLI 评测工具选择和调用序列规划 |
| 记忆机制 | LoCoMo | `locomo` | `f1` | 使用多 session 对话历史测试长期记忆与时间推理 |

这里有两个重要边界：

- EvalScope 的 `multi_if` 虽然是真正逐轮调用模型的多轮数据集，但其 `MultiTurnAdapter` 当前直接调用
  `model.generate()`，不会进入本项目的 OpenClaw external CLI runner，因此没有把它作为 LiC 替代项。
- EvalScope 的 `tool_bench` 实际是 `ToolBench-Static`。当前 adapter 没有把工具 schema 放进 external
  harness 的 instruction，OpenClaw CLI 无法看到完整工具定义。这里改用会把 API schema 同时写入文本
  prompt 的 `acebench`。它评测的是静态调用序列规划，不会真的执行 API；若要测试有状态工具执行，仍需
  额外实现 OpenClaw 工具环境与 EvalScope sample tools 的桥接。

下面的命令默认都是小样本启动配置。`EVALSCOPE_DATASETS=`、`EVALSCOPE_TASK_CONFIG=` 和
`EVALSCOPE_WORK_DIR=` 用于清除 shell 或 `.env` 中可能遗留的批量数据集、完整配置和固定输出目录，保证
当前命令中的数据集参数生效。正式评测时提高或删除 `EVALSCOPE_LIMIT`。

### 14.2 MMLU-Pro：基础知识

先使用 `computer science` 子集验证链路，避免默认同时运行全部 14 个学科：

```bash
EVALSCOPE_DATASETS= \
EVALSCOPE_TASK_CONFIG= \
EVALSCOPE_WORK_DIR= \
EVALSCOPE_DATASET=mmlu_pro \
EVALSCOPE_DATASET_ARGS='{
  "mmlu_pro": {
    "subset_list": ["computer science"],
    "few_shot_num": 0
  }
}' \
EVALSCOPE_LIMIT=5 \
EVALSCOPE_JUDGE_STRATEGY=rule \
python run.py
```

正式评测全部学科时删除 `subset_list`，或显式填写：`computer science`、`math`、`chemistry`、
`engineering`、`law`、`biology`、`health`、`physics`、`business`、`philosophy`、`economics`、
`other`、`psychology`、`history`。

### 14.3 GPQA-Diamond：复杂推理

GPQA-Diamond 没有额外 subset，默认使用 0-shot 和规则准确率：

```bash
EVALSCOPE_DATASETS= \
EVALSCOPE_TASK_CONFIG= \
EVALSCOPE_WORK_DIR= \
EVALSCOPE_DATASET=gpqa_diamond \
EVALSCOPE_DATASET_ARGS='{
  "gpqa_diamond": {
    "few_shot_num": 0
  }
}' \
EVALSCOPE_LIMIT=5 \
EVALSCOPE_JUDGE_STRATEGY=rule \
python run.py
```

### 14.4 LongMemEval：多轮对话近似项

`s` 子集约包含 115K-token 的多 session 历史。`auto` 会按 adapter 配置启用 LongMemEval 的 LLM
Judge；Judge 默认复用被评测模型，也可以使用第 13.1 节的环境变量单独指定：

```bash
EVALSCOPE_DATASETS= \
EVALSCOPE_TASK_CONFIG= \
EVALSCOPE_WORK_DIR= \
EVALSCOPE_DATASET=longmemeval \
EVALSCOPE_DATASET_ARGS='{
  "longmemeval": {
    "subset_list": ["s"],
    "few_shot_num": 0,
    "extra_params": {
      "eval_mode": "long_context",
      "history_format": "json",
      "reading_method": "con",
      "topk_context": 1000
    }
  }
}' \
EVALSCOPE_LIMIT=1 \
EVALSCOPE_JUDGE_STRATEGY=auto \
python run.py
```

这条命令测试的是一次 OpenClaw 任务读取完整历史后的回答，不是 EvalScope 与 OpenClaw 之间逐轮发送
消息。仅验证评分链路或模型上下文较小时，可以改用 `subset_list=["oracle"]`，并把 `eval_mode` 改成
`oracle_context`；该模式只提供证据 session，不能代替正式的长上下文结果。

### 14.5 ACEBench Agent：多步工具使用近似项

`agent` 子集要求模型根据 API schema 规划调用序列。OpenClaw external harness 会收到包含 schema、
初始状态和任务描述的文本 prompt：

```bash
EVALSCOPE_DATASETS= \
EVALSCOPE_TASK_CONFIG= \
EVALSCOPE_WORK_DIR= \
EVALSCOPE_DATASET=acebench \
EVALSCOPE_DATASET_ARGS='{
  "acebench": {
    "subset_list": ["agent"],
    "few_shot_num": 0
  }
}' \
EVALSCOPE_LIMIT=5 \
EVALSCOPE_JUDGE_STRATEGY=rule \
python run.py
```

OpenClaw 应按 prompt 要求输出调用列表，例如 `[ApiName(key="value")]`。该 adapter 会比较调用过程
milestone；如果输出中还包含可识别的最终状态 JSON，则同时计算 `end_state_acc`。

### 14.6 LoCoMo：长期记忆

LoCoMo 的 `qa` 子集把带日期的多 session 对话历史和问题交给 OpenClaw，使用规则 F1 评分：

```bash
EVALSCOPE_DATASETS= \
EVALSCOPE_TASK_CONFIG= \
EVALSCOPE_WORK_DIR= \
EVALSCOPE_DATASET=locomo \
EVALSCOPE_DATASET_ARGS='{
  "locomo": {
    "subset_list": ["qa"],
    "few_shot_num": 0,
    "extra_params": {
      "eval_mode": "long_context"
    }
  }
}' \
EVALSCOPE_LIMIT=1 \
EVALSCOPE_JUDGE_STRATEGY=rule \
python run.py
```

`oracle_context` 只保留答案证据，可用于验证 prompt、runner 和评分链路；正式比较 OpenClaw 的长期
记忆能力时应保持 `long_context`。

### 14.7 Baseline 与 Modified 对比

五个数据集都使用相同命令，仅切换 OpenClaw 实验环境。例如 modified 镜像：

```bash
export OPENCLAW_IMAGE=openclaw-modified:<experiment-id>
export OPENCLAW_COMPOSE_PROJECT=openclaw-eval-modified
export OPENCLAW_GATEWAY_PORT=18790
export EVALSCOPE_MODEL_ID=openclaw_modified_deepseek_v32
```

baseline 建议使用另一组项目名、端口和模型显示 ID：

```bash
export OPENCLAW_IMAGE=openclaw-baseline:2026.6.11-srcsnap
export OPENCLAW_COMPOSE_PROJECT=openclaw-eval-baseline
export OPENCLAW_GATEWAY_PORT=18789
export EVALSCOPE_MODEL_ID=openclaw_baseline_deepseek_v32
```

输出会按模型 ID、数据集和时间戳分开，例如：

```text
outputs/openclaw_baseline_deepseek_v32__gpqa_diamond/20260712_120000/
outputs/openclaw_modified_deepseek_v32__gpqa_diamond/20260712_130000/
```

正式对比时至少固定以下变量：

```bash
export EVALSCOPE_SEED=42
export EVALSCOPE_TEMPERATURE=0.0
export EVALSCOPE_BATCH_SIZE=1
export EVALSCOPE_COLLECT_PERF=true
```

其中 LongMemEval 还必须让 baseline 和 modified 使用完全相同的 Judge 模型与 Judge generation
config。任务 token 统计只包含被评测 OpenClaw harness 的模型调用，不包含 Judge 消耗。
