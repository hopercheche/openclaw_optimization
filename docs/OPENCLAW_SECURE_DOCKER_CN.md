# OpenClaw 安全 Docker 部署

目标边界：

- 不把宿主仓库以可写方式挂进容器。
- 宿主机只把当前仓库 `/home/litangchao/OpenClawPOpti` 只读挂载到容器 `/repo`。
- OpenClaw 默认工作区固定为 `/repo`，并开启 `OPENCLAW_ENFORCE_WORKSPACE_BOUNDARY=1`，API 传入 `/repo` 外的 `workspace_path` 会被拒绝。
- 可写目录仅限容器内 tmpfs：`/openclaw-runs`、`/workspace`、`/tmp`，不会写回宿主机。
- 默认使用 Docker internal network；OpenClaw app 容器不能主动访问外网，宿主通过一个无密钥 TCP gateway sidecar 访问本地端口。
- 只有显式 `run-api` 时才开启普通网络，并且运行脚本只注入 allowlist 的 API/provider 环境变量。

## 构建

```bash
scripts/openclaw_secure_docker.sh build
```

`.dockerignore` 默认采用极窄构建上下文：镜像只打入 `requirements.txt` 和无密钥 TCP gateway 脚本，不把后端源码、`.env*`、`.git`、训练/评估产物或大模型产物复制进镜像。运行时 OpenClaw 源码来自当前仓库的只读挂载 `/repo`。

## 无外网运行

```bash
scripts/openclaw_secure_docker.sh run
```

访问：

```text
http://127.0.0.1:8788/api/health
```

该模式下会启动两个容器：

```text
openclaw-secure           OpenClaw app，只连接 internal network，无外部 egress
openclaw-secure-gateway   无密钥 TCP 转发 sidecar，发布 127.0.0.1:8788
```

OpenClaw app 容器没有外部网络出口。OpenClaw 没有模型 API key 时会走本地 deterministic fallback。

该模式下宿主机可读范围只有当前仓库的只读 bind mount：

```text
/home/litangchao/OpenClawPOpti  ->  /repo:ro
```

容器内 `/workspace` 只是 scratch tmpfs，不是默认 OpenClaw 工作区，也不会写回宿主机。

## API 模式

复制示例文件：

```bash
cp deploy/openclaw-api.env.example deploy/openclaw-api.env
```

只填写需要的 provider，例如：

```text
OPENAI_API_KEY=...
OPENAI_BASE_URL=https://api.openai.com/v1
OPENCLAW_OPENAI_MODEL=gpt-4.1-mini
```

运行：

```bash
scripts/openclaw_secure_docker.sh run-api
```

注意：`run-api` 会让 OpenClaw app 容器直接使用普通 Docker bridge 网络，因为模型 API 调用需要出网。脚本只会把 allowlist 中的 API/provider 变量传入容器，但 Docker 本身不能按“只允许某个 API 域名”做强 egress 限制；如果要严格限制外联域名，需要在宿主机防火墙或一个专用 outbound proxy 上做 allowlist。

## 停止和查看

```bash
scripts/openclaw_secure_docker.sh status
scripts/openclaw_secure_docker.sh logs
scripts/openclaw_secure_docker.sh stop
```

## 安全参数

运行脚本固定使用：

```text
--read-only
--cap-drop ALL
--security-opt no-new-privileges:true
--user $(id -u):$(id -g)
--pids-limit
--memory
--cpus
--tmpfs /openclaw-runs
--tmpfs /workspace
--tmpfs /tmp
-v /home/litangchao/OpenClawPOpti:/repo:ro
-p 127.0.0.1:8788:8787
```

它不会挂载：

```text
/var/run/docker.sock
宿主 /home 的其他目录
宿主仓库可写目录
~/.ssh
~/.cache
```

这能防住 OpenClaw 通过常见权限出口篡改宿主仓库或读写宿主敏感文件。

app 容器默认使用宿主当前 UID/GID，是为了能读取当前仓库中权限较窄的源码文件；仓库挂载仍然是只读，所以该 UID 在容器内不能写回宿主仓库。gateway sidecar 不挂载仓库，也不拿 API key。

注意：当前仓库本身是只读挂载，所以仓库内文件对容器可读。如果不希望模型或工具看到某个密钥文件，不要把它放在当前仓库中；本脚本不会读取或注入 `.env.local`，API 模式只注入 `deploy/openclaw-api.env` 或当前环境中 allowlist 的 provider 变量。
