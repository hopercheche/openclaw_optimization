# OpenClawPOpti Midterm Contribution Report

This README is written as my individual contribution draft for the group midterm report. It focuses on the part I am responsible for: the Planner direction in the OpenClaw agent optimization project. The language is intentionally report-ready so it can be merged into the final group submission.

## 1. Output Goal

My goal is to build and validate an auditable planner layer for an AgentScope-style tool agent. The planner should improve multi-step task execution by choosing safer and more goal-aligned tool/action paths than a simple greedy baseline.

The expected output is not only a conceptual design. It should be a runnable prototype with API endpoints, event traces, permission decisions, benchmark tasks, evaluation reports, and enough evidence for the team to explain what has been implemented by the midterm checkpoint.

The core research question for my part is:

| 模块 | 路径 | 功能 |
|------|------|------|
| 统一模型接口 | `src/models/` | OpenAI 兼容 API + Mock 离线演示 |
| 规则路由器 | `src/router/rule_based.py` | 关键词 / 长度 / 复杂度启发式 |
| 推理 Pipeline | `src/pipeline/inference.py` | 输入 → 路由 → 调用 → 输出 |
| 评估指标 | `src/evaluation/metrics.py` | cost / latency / tier 分布 |
| **特征提取** | `src/feature/` | semantic / complexity / reasoning 特征向量 |
| API 服务 | `src/api/server.py` | FastAPI REST 接口 |
| CLI Demo | `demo.py` | 命令行演示与基准测试 |
| 特征 CLI | `extract_features.py` | 单条/批量特征提取 |

## 2. Technical Architecture and Solution Plan

The current Planner track is implemented as an audit-first runtime around AgentScope 2 concepts. The system keeps the public frontend/backend boundary simple, while isolating model-backed AgentScope execution behind an adapter layer.

```text
Frontend static console
  -> OpenClaw REST/SSE API
  -> RunManager session
  -> LocalAuditPlanner control plane
  -> optional AgentScope 2 runtime boundary
  -> OpenClaw permission gate
  -> persisted events.jsonl, state.json, and audit.md
```

The main backend modules are:

| Area | Files | Purpose |
| --- | --- | --- |
| API and run management | `backend/openclaw/server.py` | Exposes health, run creation, run lookup, event, stream, and audit endpoints. |
| Planner control plane | `backend/openclaw/planner.py` | Generates candidate steps, selects a planner path, applies permissions, simulates safe tool execution, and writes final output. |
| Search planner | `backend/openclaw/search_planner.py` | Implements `greedy_topk`, `audit_astar`, and `audit_reflexion`. |
| Permission gate | `backend/openclaw/permissions.py` | Maps each action into `allow`, `ask`, or `deny` behavior under the current permission mode. |
| Audit persistence | `backend/openclaw/storage.py`, `backend/openclaw/audit.py` | Stores run state, event logs, and Markdown audit reports. |
| AgentScope integration | `backend/openclaw/as2_adapter.py`, `backend/openclaw/as2_runtime.py`, `backend/openclaw/as2_openai.py` | Detects AgentScope, builds the optional model-backed runtime, and falls back to deterministic candidates when credentials are unavailable. |
| Benchmarking | `backend/openclaw/benchmark.py`, `backend/openclaw/model_matrix.py` | Evaluates planner strategies and provider/model configurations. |
| Learned planner hint | `backend/openclaw/planner_profile_model.py`, `scripts/train_planner_profile_model.py` | Trains a lightweight Naive Bayes profile model for no-hint routing of workflow/tool profiles. |

默认使用 `PROVIDER_MODE=mock` 和 `EMBEDDING_MODE=hash`，无需 API Key 或模型下载即可运行。

- `audit_astar`: a bounded A*-style planner that searches over candidate tool/action paths. It scores paths using impact, evidence value, reversibility, risk, permission friction, repeated actions, and missing required tools.
- `audit_reflexion`: a reflective variant that starts from the A* path and applies deterministic review/repair steps. It adds `reflection_*` events so the revision process is also visible in the audit trail.

The architecture intentionally keeps OpenClaw in charge of permission checks and evidence logging. Even when a model-backed AgentScope runtime is available, the model proposes candidates, while OpenClaw enforces the execution boundary.

## 3. Current Outputs and Progress

By the midterm checkpoint, my part has the following working outputs:

语义 embedding 模式（`EMBEDDING_MODE`）：

| 模式 | 说明 |
|------|------|
| `hash`（默认） | 本地确定性 384 维向量，无需下载，适合先跑通 |
| `bge` | `BAAI/bge-small-en-v1.5` via sentence-transformers |
| `auto` | 优先 bge，失败时回退 hash |

使用 BGE 时需额外安装：`pip install sentence-transformers`

### 3. 运行 Demo

The latest deterministic benchmark uses 88 tasks, including 61 dev tasks and 27 holdout tasks, with 3 repeats per strategy. It compares the greedy baseline against the optimized planner strategies.

| Strategy | Success rate | Mean score | Mean latency | Search events | Reflection events | Invalid tools | Hallucinated actions | Loop failures | Unsafe auto-allow |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `audit_astar` | 100.00% | 1.0000 | 0.2778s | 38.5909 | 0.0000 | 0 | 0 | 0 | 0 |
| `audit_reflexion` | 100.00% | 1.0000 | 0.2902s | 32.0455 | 4.5000 | 0 | 0 | 0 | 0 |
| `greedy_topk` | 5.68% | 0.7528 | 0.2846s | 0.0000 | 0.0000 | 0 | 0 | 0 | 0 |

On the holdout split, both optimized strategies reached 100.00% success, while `greedy_topk` reached 11.11%. This suggests that explicit planning improves the benchmark outcomes without introducing safety regressions in the local deterministic setting.

### 4. 特征提取

```bash
# 单条 query 特征
python extract_features.py extract "Explain why Transformer outperforms RNN."

# 批量提取
python extract_features.py batch --file data/sample_queries.txt -o features.json

# 运行特征模块测试
python tests/test_feature.py
```

输出 Feature Schema：

```python
{
    "embedding": [...],           # 384-d semantic vector
    "token_count": 125,
    "char_count": 680,
    "sentence_count": 4,
    "reasoning_keyword_count": 3
}
```

### 5. 启动 API 服务

## 4. Evidence of Current Outputs

The current evidence is stored directly in the repository:

| Evidence type | Location |
| --- | --- |
| Planner runtime code | `backend/openclaw/planner.py` |
| Planner search algorithms | `backend/openclaw/search_planner.py` |
| Permission gate | `backend/openclaw/permissions.py` |
| AgentScope 2 adapter/runtime | `backend/openclaw/as2_adapter.py`, `backend/openclaw/as2_runtime.py` |
| Benchmark runner | `backend/openclaw/benchmark.py` |
| Benchmark task suites | `benchmarks/tasks/*.json` |
| Latest benchmark report | `data/benchmarks/20260622T144217Z/report.md` |
| Latest benchmark metrics | `data/benchmarks/20260622T144217Z/metrics.json` |
| Per-run audit examples | `data/benchmarks/20260622T144217Z/artifacts/**/audit.md` |
| Planner profile model | `data/planner_models/profile_policy_model.json` |
| Planner profile model report | `data/planner_models/profile_policy_report.md` |
| Architecture notes | `docs/AS2_ARCHITECTURE.md` |
| Benchmark design notes | `docs/PLANNER_BENCHMARKS.md` |
| MVP plan | `docs/MVP_PLAN.md` |

Useful reproduction commands:

- `GET /health` — 健康检查
- `POST /query` — 路由 + 推理（完整链路）
- `POST /route` — 仅路由决策（不调用模型）
- `POST /features` — 特征提取（semantic + complexity + reasoning）
- `POST /benchmark` — 批量基准测试

No final UI screenshots are committed yet. Before the group report is submitted, I can capture screenshots of the frontend console, event timeline, and generated `audit.md` page as visual evidence.

## 5. Risks, Challenges, and Limitations

The main limitation is that the strongest evidence currently comes from deterministic local benchmarks. The AgentScope 2 model-backed path exists, but real provider-quality comparisons still require stable API keys and repeated evaluation under the same benchmark protocol.

The second limitation is that `audit_astar` is a bounded A*-style search, not a full LATS or MCTS planner. It is intentionally simpler and easier to audit, but it does not yet include full rollout simulation or backpropagation.

The third risk is benchmark coverage. The current suite covers workspace grounding, permission traps, safety, deployment risk, mobile/CLI/MCP-style workflows, policy-tool-agent tasks, API planning tasks, and skill workflows. However, final evaluation should include more repo-grounded multi-step tasks that resemble realistic OpenClaw usage.

The fourth limitation is scope. My work focuses on the Planner direction. The broader capstone may also include Strategist and Architect directions, but those need to be integrated carefully so the final system does not become a collection of disconnected demos.

## 6. Plan and Goal for the Final Submission

```
strategist-mvp/
├── config/models.yaml      # 模型池与路由阈值
├── data/sample_queries.txt # 样例测试数据
├── src/
│   ├── models/             # LLM Provider 抽象层
│   ├── router/             # Rule-based Router
│   ├── pipeline/           # 推理 Pipeline
│   ├── evaluation/         # 评估指标
│   ├── feature/            # 特征提取模块
│   │   ├── semantic.py     # 384-d embedding
│   │   ├── complexity.py   # token/char/sentence
│   │   ├── reasoning.py    # 推理关键词计数
│   │   └── extractor.py    # 统一接口
│   └── api/                # FastAPI 服务
├── extract_features.py     # 特征提取 CLI
├── demo.py                 # 路由 Demo CLI
├── run_server.py           # API 服务入口
└── requirements.txt
```

1. Run model-backed AS2/provider benchmarks with real credentials and compare them against the deterministic fallback.
2. Expand benchmark tasks with more realistic OpenClaw workflows, especially repo-grounded editing, validation, and deployment-safety scenarios.
3. Improve the reflective planner only if it beats or matches `audit_astar` under the same holdout protocol.
4. Add final report evidence, including frontend screenshots, benchmark tables, generated audit reports, and a concise architecture diagram.

| 阶段 | 内容 |
|------|------|
| Phase 1 | Rule-based Router MVP |
| **Phase 2 (当前)** | Feature Extraction（semantic / complexity / reasoning） |
| Phase 3 | Feature-based Router（ML 分类训练） |
| Phase 4 | Cost-aware Routing（LLM-as-Judge 偏好标注） |
| Phase 5 | FrugalGPT Cascade（small → mid → large 级联） |
| Phase 6 | 系统评估与消融实验 |

## 7. My Role and Contribution in the Team

本 MVP 设计为可插拔模块，后续可通过 OpenClaw Plugin SDK 封装为 Provider Plugin，替换默认的单模型调用路径。
