# The Strategist MVP

OpenClaw Capstone 方向一：**最优 LLM 路由** — 第一阶段 MVP（Rule-based Routing）

## 目标

在保持回答质量的前提下，通过规则路由器将不同难度的请求分配给 small / mid / large 三档模型，打通完整推理链路并建立基础评估指标。

## 架构

```
用户输入 → Rule-based Router → 模型选择 (small/mid/large) → LLM API → 输出 + 指标
```

### 模块说明

| 模块 | 路径 | 功能 |
|------|------|------|
| 统一模型接口 | `src/models/` | OpenAI 兼容 API + Mock 离线演示 |
| 规则路由器 | `src/router/rule_based.py` | 关键词 / 长度 / 复杂度启发式 |
| 推理 Pipeline | `src/pipeline/inference.py` | 输入 → 路由 → 调用 → 输出 |
| 评估指标 | `src/evaluation/metrics.py` | cost / latency / tier 分布 |
| API 服务 | `src/api/server.py` | FastAPI REST 接口 |
| CLI Demo | `demo.py` | 命令行演示与基准测试 |

## 快速开始

### 1. 安装依赖

```bash
cd strategist-mvp
pip install -r requirements.txt
```

### 2. 配置（可选）

```bash
cp .env.example .env
```

默认使用 `PROVIDER_MODE=mock`，无需 API Key 即可运行 Demo。

接入真实 API 时：

```env
PROVIDER_MODE=openai
OPENAI_API_KEY=sk-...
OPENAI_BASE_URL=https://api.openai.com/v1

# 可选：自定义三档模型
SMALL_MODEL=gpt-4o-mini
MID_MODEL=gpt-4o
LARGE_MODEL=gpt-4
```

也支持 OpenRouter、DashScope 等 OpenAI 兼容端点。

### 3. 运行 Demo

```bash
# 完整 Demo（5 条样例 query + 基准报告）
python demo.py demo

# 单条查询
python demo.py query "请解释为什么梯度下降能够收敛"

# 基准测试
python demo.py benchmark --file data/sample_queries.txt -o report.json
```

### 4. 启动 API 服务

```bash
python run_server.py
# 访问 http://localhost:8000/docs 查看 Swagger UI
```

API 端点：

- `GET /health` — 健康检查
- `POST /query` — 路由 + 推理（完整链路）
- `POST /route` — 仅路由决策（不调用模型）
- `POST /benchmark` — 批量基准测试

## 路由规则

MVP 使用加权启发式评分（可在 `config/models.yaml` 调整）：

1. **推理关键词**（权重 0.4）：why / compare / explain / prove / 分析 / 证明 等
2. **输入长度**（权重 0.3）：短 → small，中 → mid，长 → large
3. **复杂度特征**（权重 0.3）：多句、多问号、代码块、数学符号

综合得分 < 0.35 → **small**，0.35–0.65 → **mid**，≥ 0.65 → **large**

## 评估指标

- **成本**：每 query 的 token 成本（USD）及相对 always-large 的节省比例
- **延迟**：端到端 latency (ms)
- **路由分布**：small / mid / large 使用比例

## 项目结构

```
strategist-mvp/
├── config/models.yaml      # 模型池与路由阈值
├── data/sample_queries.txt # 样例测试数据
├── src/
│   ├── models/             # LLM Provider 抽象层
│   ├── router/             # Rule-based Router
│   ├── pipeline/           # 推理 Pipeline
│   ├── evaluation/         # 评估指标
│   └── api/                # FastAPI 服务
├── demo.py                 # CLI 入口
├── run_server.py           # API 服务入口
└── requirements.txt
```

## 后续阶段（路线图）

| 阶段 | 内容 |
|------|------|
| **Phase 1 (当前)** | Rule-based Router MVP |
| Phase 2 | Feature-based Router（embedding + ML 分类） |
| Phase 3 | Cost-aware Routing（LLM-as-Judge 偏好标注） |
| Phase 4 | FrugalGPT Cascade（small → mid → large 级联） |
| Phase 5 | 系统评估与消融实验 |

## 与 OpenClaw 集成

本 MVP 设计为可插拔模块，后续可通过 OpenClaw Plugin SDK 封装为 Provider Plugin，替换默认的单模型调用路径。

## 运行
cd strategist-mvp
pip3 install -r requirements.txt

# 无需 API Key 的离线 Demo（默认 mock 模式）
python3 demo.py demo

# 单条查询
python3 demo.py query "请解释为什么梯度下降能够收敛"

# 基准测试
python3 demo.py benchmark --file data/sample_queries.txt -o report.json

# 启动 API 服务 → http://localhost:8000/docs
python3 run_server.py