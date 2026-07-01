# DeepSpec/DSpark 与 Agent_Planner 深度融合方案

## 目标

把 `deepseek-ai/DeepSpec` 从“可参考论文项目”升级为 `Agent_Planner` 的真实 Stage11 加速路线：保留 Stage7 planner 的 schema/overlap 质量，用 DSpark draft model 和 confidence-scheduled speculative decoding 降低真实 serving 延迟。

关键约束：

```text
当前最佳 target: models/20260627T-stage7-verifier-combined3k-500-merged
target 架构: Qwen2ForCausalLM / model_type=qwen2
DeepSpec 官方支持: qwen3 / gemma4
官方默认 Qwen3-4B target cache: README 提示约 38 TB，默认 8 GPU
本仓库资源假设: AgentOpti + GPU1，产物放在 Agent_Planner 下
```

因此融合路线不是直接跑官方默认脚本，而是：

```text
DeepSpec 原生代码复用
  + OpenClaw planner prompt/cache 适配
  + Qwen2 DSpark port
  + planner 专用 greedy/exact speculative evaluator
  + 1k/10k 小缓存训练和在线延迟验证
```

## 已完成的工程融合

### 1. DeepSpec 官方源码快照

已把官方项目作为 ignored 外部快照放入：

```text
data/litangchao/OpentClawOpti/Agent_Planner/external/DeepSpec
```

当前直接复用的 DeepSpec 组件：

| DeepSpec 组件 | 复用方式 | 用途 |
| --- | --- | --- |
| `deepspec.data.target_cache_dataset` | 直接 import | 写 target hidden-state cache、manifest、index、shard |
| `deepspec.modeling.dspark.loss` | 直接 import | DSpark CE/L1/confidence loss |
| `deepspec.trainer.base_trainer` | 直接 import | FSDP/optimizer/checkpoint/training loop |
| `deepspec.modeling.dspark.common` | 直接 import | anchor sampling、attention mask、confidence utilities |
| `deepspec.modeling.dspark.markov_head` | 直接 import | Markov head |

### 2. Qwen2 DSpark port

DeepSpec 官方只有 Qwen3/Gemma4 DSpark 实现，而 Stage7 是 Qwen2。因此新增：

```text
deepspec_openclaw/modeling/dspark/qwen2/config.py
deepspec_openclaw/modeling/dspark/qwen2/modeling.py
deepspec_openclaw/trainer/qwen2_dspark_trainer.py
configs/stage11_dspark_qwen2_planner_smoke.py
```

实现方式：

```text
以 DeepSpec 的 Qwen3DSparkModel 为模板
替换为 transformers.models.qwen2.modeling_qwen2
保留 DSpark draft backbone、Markov head、confidence head、loss 接口
修复 Qwen2Config 兼容差异：attention_bias 缺省时按 False
mask_token_id 使用 Qwen2 embedding 中存在但 tokenizer 不自然产生的 151666
```

验证：

```text
Qwen2DSparkModel 实例化通过：
Qwen2DSparkModel 3 [12] 1 151666
```

### 3. Planner 专用 target-cache builder

新增：

```text
scripts/build_deepspec_planner_cache.py
```

它不使用 DeepSpec 默认 `ConversationCollator/chat_template`，原因是默认 parser 会重新渲染 qwen chat 并插入通用 system prompt，可能破坏我们 Stage7 已训练的 planner prompt。新脚本直接读取 OpenClaw SFT `text` 字段：

```text
prompt = text 到 <|im_start|>assistant\n 为止
target = assistant JSON 到末尾
input_ids = prompt_ids + target_ids
loss_mask = prompt 0 / target 1
超长时优先保留 target，并从 prompt 左侧截断
```

它复用 DeepSpec 的 target-cache writer，输出仍是 DeepSpec-compatible cache：

```text
manifest.json
samples.idx
shard-*.bin
```

### 4. Cache 预算验证

在 1k 样本、`max_length=384`、target layers `[12,24]` 下完成 estimate：

```text
eval_runs/20260629T-stage11-deepspec-cache-estimate-1k-l384-layer12-24
sample_count: 1000
mean_seq_len: 358.90
total_seq_len: 358901
hidden_size: 2048
num_target_layers: 2
estimated_cache_gib: 4.1093
```

按同样配置线性估算：

| 样本量 | 估算 cache |
| ---: | ---: |
| 1k | 4.11 GiB |
| 3k | 12.33 GiB |
| 10k | 41.09 GiB |

这意味着可以在“不超过 50G”的边界内做 10k 级 planner-specific DSpark 训练；如果改成 1 个 target layer，还能进一步降缓存。

### 5. GPU1 smoke cache

真实 GPU1 生成 8 样本 target cache 成功：

```text
eval_runs/20260629T-stage11-deepspec-cache-smoke8-l384-layer12-24/target_cache
num_samples: 8
target_layer_ids: [12, 24]
hidden_size: 2048
estimated_cache_gib: 0.0318
```

### 6. DeepSpec trainer 1-step smoke

补了最小依赖：

```text
tensorboard
prettytable
```

没有安装 DeepSpec 全量 requirements，避免替换当前 torch/transformers。

随后用 GPU1 跑通：

```text
target cache: eval_runs/20260629T-stage11-deepspec-cache-smoke8-l384-layer12-24/target_cache
config: configs/stage11_dspark_qwen2_planner_smoke.py
max_train_steps: 1
loss: 4.3045
checkpoint: models/openclaw_agent_planner/stage11_dspark_qwen2_planner_smoke/step_1
```

这证明四段链路已经真实连通：

```text
OpenClaw planner SFT text
  -> planner direct target cache
  -> DeepSpec CacheDataset/BaseTrainer/loss
  -> Qwen2DSparkModel
  -> checkpoint
```

## 融合后的系统位置

Stage11 不替代 Stage7/Stage10，而是成为 serving-speed 层：

```text
请求
  -> Stage7 target planner
      -> DSpark Qwen2 draft 提案 JSON token block
      -> Stage7 exact verify
      -> schema/quality guard
  -> 可选 Stage10 structural-risk route
      -> 仅 long/script/multiline 风险时请求 Stage9
```

推荐顺序：

```text
先加速 Stage7 单模型
再和 Stage10 suppressany route 合并
最后才考虑 Stage9 secondary 的 speculative 加速
```

原因：Stage10 当前 Stage9 请求率只有 1.80%，主要延迟仍来自 Stage7 primary；先加速 primary 的收益更直接。

## 深度优化点

### A. Planner-specific target layer 搜索

DeepSpec 默认 Qwen3 使用多层 `[1,9,17,25,33]`，但我们不能照搬。Qwen2 Stage7 应做小网格：

| 配置 | Cache 成本 | 预期 |
| --- | ---: | --- |
| `[24]` | 低 | 快速 smoke，可能足够预测 JSON 格式 |
| `[12,24]` | 中 | 当前默认，平衡语义与成本 |
| `[8,16,24]` | 高 | 可能提升 command token acceptance |

晋级指标不是 loss，而是 1k online `verify_rate / accept_len / latency / overlap`。

### B. Confidence schedule 改成 planner-aware

DSpark 原生 confidence threshold 是统一阈值。Planner JSON 可以做 token 区域分层：

```text
JSON 固定结构 token: threshold 低，允许 block 7-8
analysis/plan 普通文本: threshold 中，允许 block 4-7
commands.keystrokes: threshold 高，block 1-3
数字、路径、引号内 shell 片段: threshold 最高，必要时退回 Stage7 单步
```

这个比通用 benchmark 更适合 planner，因为 schema token 很可预测，但 command token 一错就伤 overlap。

### C. Greedy exact verify 而不是 sampling verify

OpenClaw planner serving 使用 greedy Transformers batch，不应照搬 DeepSpec 通用 sampling evaluator。需要新增 planner 专用 evaluator：

```text
draft argmax proposal
target argmax exact verify
accepted prefix 写入输出
拒绝时立即用 target token
保持最终文本等价于 Stage7 greedy 输出
```

这样理论上 schema/overlap 不应该低于 Stage7；唯一风险是实现 bug 或 stop/position/cache 不一致。

### D. 与 Stage10 route 的组合

组合方式不能是“Stage7 speculative + Stage9 speculative 全开”。先做：

```text
Stage7 speculative primary
Stage10 suppressany route policy 原样保留
Stage9 secondary 仍普通 Transformers
```

只有当 Stage7 speculative 的输出与 Stage7 baseline 完全等价或指标不降，才考虑 Stage9 speculative。

### E. 训练数据不要直接上 100k

缓存成本和训练信号都要求分阶段：

| 阶段 | 数据 | 目的 |
| --- | ---: | --- |
| smoke | 128 | 验证 cache/trainer/evaluator |
| pilot | 1k | 看 acceptance 是否超过 Stage9 proxy 下限 |
| main | 10k | 进入真实 latency 对比 |
| expand | 20k+ | 仅当 10k 明显有效再做 |

## 已完成的下一轮 smoke

已继续把 8 样本 smoke 扩成 128 样本短训，并新增 OpenClaw planner 专用 speculative benchmark：

```text
scripts/benchmark_dspark_speculative_planner.py
eval_runs/20260629T-stage11-deepspec-cache-train128-l384-layer12-24
models/openclaw_agent_planner/stage11_dspark_qwen2_planner_128x20/step_20
eval_runs/20260629T-stage11-dspark-speculative-128x20-heldout5001-8
eval_runs/20260629T-stage11-stage7-baseline-heldout5001-8-max128-batch1
eval_runs/20260630T-stage11-targetonly-loop-heldout5001-8-eager
eval_runs/20260630T-stage11-dspark-speculative-128x20-heldout5001-8-eager
eval_runs/20260630T-stage11-dspark-speculative-128x20-heldout5001-8-seqverify
eval_runs/20260630T-stage11-dspark-speculative-128x20-heldout5001-8-seqverify-margin5
```

128 cache 成功生成，估算 0.5312 GiB；20 step 短训成功，loss 从 4.2659 降到 3.0584。但 heldout5001 8 条 smoke 显示当前 draft 不能晋级：

| 路线 | Schema | Overlap | Mean request | Verify rate | Acceptance |
| --- | ---: | ---: | ---: | ---: | --- |
| Stage7 baseline batch1 max128 | 87.50% | 0.0754 | 1.9151s | n/a | n/a |
| DSpark 128x20 max128 | 50.00% | 0.0837 | 2.6567s | 0.1337 | pos0 6.94%，其余 0 |

训练切片也没有显著改善：train line1 4 条 pos0 acceptance 约 7.17%，seq384 对齐后约 6.48%，后续 block 位置仍为 0。

20260630 又做了 evaluator 级修复和复测：

```text
新增 repetition_penalty=1.05 对齐 Stage7 generation_config
target prefill 显式 attention_mask/cache_position
新增 Qwen2 4D causal block mask
新增 --verify-mode block/sequential
新增 --accept-margin
```

| 路线 | Schema | Overlap | Mean request | Verify rate | Exact / Acceptance |
| --- | ---: | ---: | ---: | ---: | --- |
| target-only eager loop | 100.00% | 0.1060 | 2.7194s | 1.0000 | HF exact 87.50% |
| DSpark block verify eager | 100.00% | 0.1060 | 2.7484s | 0.1320 | HF exact 37.50%，pos0 5.61% |
| DSpark sequential verify eager | 100.00% | 0.1060 | 2.7956s | 0.1316 | HF exact 87.50%，pos0 5.29%，其余 0 |
| DSpark sequential verify margin5 | 100.00% | 0.1060 | 2.7602s | 0.1308 | HF exact 87.50%，pos0 4.63%，其余 0 |

这个结果把问题拆开了：target-only/eager 已经不再是 exact=0 的状态，sequential verify 能作为 correctness 诊断；但 block verify 仍会偏离 sequential/HF，不能作为晋级口径。更重要的是，当前 draft 的真实 acceptance 仍只有首位约 5%，后续位置为 0，说明短训 draft 本身不够强。

## 更新后的执行计划

1. 先用 `--verify-mode sequential` 做 1k diagnostic，记录 target-only exact、draft acceptance、schema/overlap 和真实 latency。
2. 在 sequential 1k 证明 acceptance 有明显起跳前，不扩大到 10k 训练；最多做 1k cache 的小配置对照。
3. 训练 Qwen2DSpark draft 时增加结构对照：
   - target_layer_ids `[24]` vs `[12,24]` vs `[8,16,24]`
   - draft layers 2 vs 4
   - block size 4 vs 7
   - confidence head 关闭 vs 开启
4. 对比：
   - Stage7 Transformers baseline 1k
   - Stage11 DSpark sequential diagnostic 128/1k
   - Stage11 DSpark block speed probe，仅在 block verify 与 sequential/HF 等价后启用
   - Stage11 DSpark speculative + Stage10 suppressany route
5. 晋级门槛：
   - schema_valid_rate = 100.00%
   - command_overlap_mean >= 0.2294
   - mean_amortized_request_seconds 至少比 Stage7 降 8%-15%
   - generated JSON 与 Stage7 greedy 差异必须可解释

## 当前结论

```text
DeepSpec 已经不是“只能参考”的外部项目，而是进入了 Agent_Planner 的真实训练/serving 实验路线。
已完成源码快照、Qwen2 DSpark port、planner direct cache builder、GPU1 target-cache、DeepSpec trainer、speculative benchmark。
负结果也已经明确：128x20 draft acceptance 太低，sequential 诊断下也没有速度收益，不能晋级。
下一步关键不是继续盲目加训练步数，而是先用 sequential 1k 诊断筛掉弱 draft，再用 1k cache 做层配置和 draft 容量对照。
```

## 20260630 继续优化结果

在上一轮确认 128x20 太弱后，继续比较了 draft 容量和训练步数：

| 配置 | 训练结果 | 16 条 sequential 诊断 | 决策 |
| --- | --- | --- | --- |
| 128x20 d4 | loss 5.1081 -> 3.0957 | verify_rate 0.1320，acceptance `[5.62%,0,0,0,0,0,0]`，mean 2.8588s | 否：容量翻倍不解决 acceptance |
| 128x100 d2 | loss 4.2659 -> 2.5798 | verify_rate 0.1698，acceptance `[31.25%,4.27%,0.34%,0,0,0,0]`，mean 2.6625s | 有效：训练步数是关键变量 |
| 128x200 d2 | loss 4.2659 -> 1.9220 | verify_rate 0.2280，acceptance `[41.93%,15.05%,8.85%,6.73%,4.90%,3.34%,2.04%]`，mean 2.5871s | 当前最佳 Stage11 draft |

128x200 d2 进一步跑了 64 条 sequential 诊断：

```text
schema_valid_rate = 68.75%
command_overlap_mean = 0.1377
mean_amortized_request_seconds = 2.5221s
verify_rate = 0.2313
acceptance = [44.34%, 15.42%, 8.90%, 6.47%, 4.66%, 3.27%, 2.36%]
target_greedy_exact_match_rate = 78.12%
```

这个结果仍不能晋级 serving：schema/overlap 离 Stage7 1k 门槛很远，而且 sequential verify 不是最终低延迟 block speed path。但它改变了 Stage11 的下一步判断：现在不应继续 20-step smoke，也不应优先 4-layer；应先扩数据。

下一步执行顺序：

1. 先清理 rejected/superseded 大模型，当前 `Agent_Planner` 树约 94G，已超过 50G 约束。
2. 构建 1k `[12,24]` target cache；估算大小 4.1093GiB。
3. 用 2-layer、200 step 起步训练 1k draft。
4. 先跑 64 条 sequential，对比 128x200；若 acceptance 继续提升，再跑 1k heldout diagnostic。
5. 在 block verify 与 sequential/HF 等价前，不把 block speed probe 作为晋级证据。
