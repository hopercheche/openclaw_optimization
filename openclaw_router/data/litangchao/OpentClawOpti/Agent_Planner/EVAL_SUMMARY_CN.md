# Agent Planner 评估总结

更新：2026-06-26

## 大规模 SFT 运行

```text
run: 20260623T063028Z-qwen25-3b-gpu1-stream200k-5k
base: Qwen2.5-3B-Instruct 本地缓存
adapter: models/20260623T063028Z-qwen25-3b-gpu1-stream200k-5k/final_adapter
train_file: processed/qwen_terminal_toolbench_sft.jsonl
samples: 200,000 个流式样本
steps: 5,000 / 5,000
runtime: 约 3:31:31
last logged loss at step 5000: 0.3573
```

## Heldout SFT 评估

Heldout 切片从 `processed/qwen_terminal_toolbench_sft.jsonl` 的第 300001 行开始，位于前 200k 流式训练窗口之外。

```text
eval_run: eval_runs/20260623T143655Z-base-vs-lora-heldout
loss_examples: 64
generation_examples: 16
max_new_tokens: 256
gpu: GPU1 / NVIDIA L20
```

| 模型 | Loss | PPL | 有效 JSON | Schema 有效 | 平均 TTFT | 生成 tok/s |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| base | 1.811775 | 6.1213 | 12.50% | 0.00% | 0.0446s | 60.63 |
| LoRA adapter | 1.056539 | 2.8764 | 0.00% | 0.00% | 0.0619s | 27.88 |

Adapter 相比 base 的 loss 相对下降 41.68%，说明这次 SFT 运行学到了 heldout token 分布。不过，在 256-token 生成预算下，adapter 经常以很长的 `<think>` 块开头，并在输出完整 JSON 对象之前被截断。

仅 adapter 的长窗口检查：

```text
eval_run: eval_runs/20260623T144420Z-lora-heldout-gen768
generation_examples: 8
max_new_tokens: 768
valid_json_rate: 50.00%
schema_valid_rate: 50.00%
mean_ttft: 0.0966s
mean_generation_seconds: 21.6793s
mean_tokens_per_second: 28.28
```

结论：这个 adapter 是有用的 warm-start checkpoint，但还不是快速响应的生产 planner。下一轮训练应该把 target 转成简洁的 JSON-only planner action，移除或 mask `<think>` 片段，并把严格 schema 有效性作为一等评估指标。

## JSON-Only 优化轮次

第一个 LoRA checkpoint 在 GPU1 上继续训练了三轮：

```text
stage2: JSON-only targets, 200k source rows, 1,000 steps
stage3: strict JSON prompt targets, 100k source rows, 500 steps
stage4: strict JSON prompt + at most 3 commands + shorter action fields, 100k source rows, 500 steps
stage5: stage4 continued on short-command targets, dropping commands with keystrokes longer than 160 chars, 100k source rows, 500 steps
stage6: stage5 continued on compact action2 targets, dropping commands with keystrokes longer than 120 chars, 100k source rows, 500 steps
```

当前推荐 adapter：

```text
models/20260624T130000Z-qwen25-3b-gpu1-shortcmd120-action2-stage6-500/final_adapter
```

### 阶段对比

下表所有行都使用从原始 Qwen Terminal ToolBench SFT 文件第 300001 行开始生成的 heldout 数据。Stage2-4 使用 action-level target surface；stage5-6 使用逐步缩短的 command/action target surface。

| 运行 | 评估 | Max New Tokens | 生成样本数 | Schema 有效 | 平均 TTFT | 平均生成时间 | 平均 Tokens | 生成 tok/s |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| stage2 JSON-only | `20260624T080900Z-jsononly-stage2-heldout` | 256 | 16 | 31.25% | 0.0618s | 7.9832s | 226.56 | 28.36 |
| stage3 strict prompt | `20260624T084200Z-strict-json-stage3-heldout` | 256 | 16 | 31.25% | 0.0633s | n/a | 218.69 | 27.78 |
| stage4 action3 | `20260624T101000Z-action3-stage4-heldout` | 256 | 16 | 87.50% | 0.0672s | 7.1978s | 202.00 | 28.04 |
| stage4 action3，更宽检查 | `20260624T103100Z-action3-stage4-heldout-64gen` | 256 | 64 | 76.56% | 0.0767s | 7.2388s | 204.22 | 28.20 |
| stage4 action3，短预算 | `20260624T102000Z-action3-stage4-heldout-192` | 192 | 16 | 43.75% | 0.0828s | 6.2234s | 177.31 | 28.48 |
| stage5 shortcmd160 | `20260624T114000Z-shortcmd160-stage5-heldout-64gen` | 256 | 64 | 96.88% | 0.0703s | 5.7663s | 164.28 | 28.49 |
| stage5 shortcmd160，短预算 | `20260624T115000Z-shortcmd160-stage5-heldout-192-64gen` | 192 | 64 | 87.50% | 0.0708s | 5.6561s | 159.63 | 28.22 |
| stage6 shortcmd120 action2 | `20260624T133000Z-shortcmd120-action2-stage6-heldout-192-64gen` | 192 | 64 | 96.88% | 0.0708s | 4.6234s | 128.66 | 27.82 |
| stage6 shortcmd120 action2，短预算 | `20260624T134000Z-shortcmd120-action2-stage6-heldout-160-64gen` | 160 | 64 | 93.75% | 0.0704s | 4.5087s | 127.11 | 28.19 |
| stage6 merged full model | `20260625T002600Z-stage6-merged-transformers-192-64gen` | 192 | 64 | 100.00% | 0.0483s | 2.1153s | 127.58 | 60.30 |
| stage6 merged Transformers batch8 | `20260625T034500Z-stage6-transformers-batch8-192-64gen` | 192 | 64 | 100.00% | n/a | 0.7403s amortized | 127.59 | 172.35 |
| stage6 merged Transformers batch16 | `20260625T035000Z-stage6-transformers-batch16-192-64gen` | 192 | 64 | 100.00% | n/a | 0.4462s amortized | 123.97 | 277.85 |
| stage6 merged Transformers batch32 | `20260625T035500Z-stage6-transformers-batch32-192-64gen` | 192 | 64 | 98.44% | n/a | 0.6790s amortized | 124.22 | 182.94 |
| stage6 merged Transformers batch16，256 样本 baseline | `20260625T054500Z-stage6-transformers-batch16-192-256gen` | 192 | 256 | 100.00% | n/a | 0.3621s amortized | 125.93 | 347.79 |
| stage6 merged Transformers batch16，按 prompt 排序 | `20260625T055000Z-stage6-transformers-batch16-256-sort-256gen` | 256 | 256 | 100.00% | n/a | 0.2638s amortized | 126.90 | 481.10 |
| stage6 merged Transformers batch16，seq768 排序速度候选 | `20260625T055500Z-stage6-transformers-batch16-256-seq768-sort-256gen` | 256 | 256 | 100.00% | n/a | 0.2420s amortized | 125.67 | 519.25 |
| stage6 merged Transformers batch16，224-token 排序负向检查 | `20260626T093000Z-stage6-transformers-batch16-224-sort-256gen` | 224 | 256 | 99.61% | n/a | 0.2634s amortized | 126.89 | 481.76 |
| stage6 merged Transformers batch32，按 prompt 排序 | `20260626T093500Z-stage6-transformers-batch32-256-sort-256gen` | 256 | 256 | 100.00% | n/a | 0.2173s amortized | 125.52 | 577.51 |
| stage6 merged Transformers batch64，按 prompt 排序 | `20260626T094000Z-stage6-transformers-batch64-256-sort-256gen` | 256 | 256 | 100.00% | n/a | 0.2244s amortized | 127.23 | 566.87 |
| stage6 merged vLLM batch1 | `20260625T010100Z-stage6-vllm-batch1-192-64gen` | 192 | 64 | 59.38% | n/a | 0.6635s amortized | 63.42 | 95.58 |
| stage6 merged vLLM batch8 | `20260625T010800Z-stage6-vllm-batch8-192-64gen` | 192 | 64 | 60.94% | n/a | 0.2157s amortized | 65.23 | 302.50 |
| stage6 merged vLLM context1280 batch16 text prompt | `20260626T084500Z-stage6-vllm-context1280-batch16-textprompt-256-256gen` | 256 | 256 | 97.66% | n/a | 0.1712s amortized | 108.34 | 632.74 |
| stage6 merged SGLang 0.5.8 HTTP conc16 default sampling | `20260626T090500Z-stage6-sglang058-http-conc16-prompt1000-256-128gen` | 256 | 128 | 98.44% | n/a | 0.1260s amortized | 109.87 | 872.10 |
| stage6 merged SGLang 0.5.8 HTTP conc16 greedy sampling | `20260626T092000Z-stage6-sglang058-http-conc16-greedy-prompt1024-224-128gen` | 224 | 128 | 96.09% | n/a | 0.1280s amortized | 106.72 | 833.54 |

Stage4 是第一个能在 256-token 预算下稳定生成有效 planner 形态 JSON 的 checkpoint。64 样本检查低于 16 样本运行，但仍然确认了相比 action-level 重写之前 0-31% schema 有效率区间的实质跃升。

Stage5 是当前最佳 checkpoint。过滤掉超过 160 字符的命令，直接解决了 stage4 的主要失败模式：模型开始写很长的 heredoc/script command 后 JSON 被截断。在 64 样本检查中，stage5 将 schema 有效率从 76.56% 提升到 96.88%，并把平均生成时间从 7.2388s 降到 5.7663s。

192-token 的 stage5 检查可用，但不推荐作为默认值：相比 256-token 运行只节省约 0.11s，却把 schema 有效率从 96.88% 降到 87.50%。

Stage6 是新的最佳 checkpoint。将 target 缩减为最多两个短命令，配合 120 字符命令 keystroke 过滤以及 160 字符 analysis/plan 字段限制，在 192-token 预算下保持了 96.88% schema 有效率，并将平均生成时间降到 4.6234s。160-token 预算可用但不是默认值，因为它只节省约 0.11s，却把 schema 有效率降到 93.75%。

把 stage6 LoRA 合并到 full model 后，得到了承载 serving 优化的稳定基础。在同一块 GPU1、相同 64 个样本、相同 192-token 预算下，merged Transformers 运行将平均生成时间从 4.6234s 降到 2.1153s，同时把 schema 有效率从 96.88% 提升到 100.00%。Token 吞吐从 27.82 tok/s 提升到 60.30 tok/s，TTFT 从 0.0708s 降到 0.0483s。

Batched Transformers generation 是当前最佳的高准确率 serving 路线。Batch8 保持 100% schema 有效，并把摊销请求延迟降到 0.7403s。Batch16 更好：它保持 100% schema 有效，将摊销请求延迟降到 0.4462s，并在 GPU1 上达到 277.85 tok/s。早期未排序 batch32 检查不推荐，因为 schema 有效率降到 98.44%，但后续按 prompt 排序的 batch32 检查修复了这个失败模式。

Transformers 路线又通过 prompt-length batching 得到改进。按 token 长度对 prompt 排序后再 batching，可以在保持相同模型和 decoding stack 的同时减少 left-padding 工作量。在更宽的 256 样本检查上，原始顺序的 batch16 baseline 使用 `max_new_tokens=192` 时保持 100% schema 有效，摊销每请求 0.3621s。Batch16 排序并使用 `max_new_tokens=256` 时保持 100% schema 有效，命令重合度基本不变（`0.1399` vs `0.1393`），并将摊销请求延迟降到 0.2638s。新的高准确率默认值现在是 `batch_size=32`、`max_seq_length=1024`、`max_new_tokens=256`、`dtype=bf16`、`sort_by_prompt_length=true`：它保持 100% schema 有效，把命令重合度提升到 `0.1445`，并将摊销请求延迟降到 0.2173s。Batch64 也保持了 schema 有效，但因为 prompt padding 从 6.71% 上升到 12.83%，所以比 batch32 更慢。更快的 `max_seq_length=768` 排序候选达到 0.2420s，并保持 100% schema 有效，但命令重合度更低（`0.1333`），因此在 task-level evaluation 通过之前，它应保留为速度优先候选。

被拒绝的 serving 捷径：`max_new_tokens=152/160` 在 64 个样本上看起来不错，但在 128 个样本上 schema 有效率下降；`fp16` 将 schema 有效率降到 92.19%；`max_seq_length=512` 和 `704` 在某些检查中更快，但丢失了 schema 有效性或命令重合度。

Merged checkpoint：

```text
models/20260625T002525Z-qwen25-3b-stage6-merged
```

Merge metadata：

```text
models/20260625T002525Z-qwen25-3b-stage6-merged/merge_config.json
```

vLLM 被有意安装在单独的 serving 环境中，而不是 `AgentOpti` 中，因此上面的 merged Transformers 运行仍然是干净的 full-model benchmark：

```text
AgentOptiVLLM: vllm 0.18.1, torch 2.10.0+cu128
AgentOpti: unchanged, torch 2.11.0+cu128
```

修复 context budget 后，vLLM serving 实验有所改善。最初的 vLLM 运行使用 `max_model_len=1024` 和 `max_new_tokens=192` 预算，只剩下 832 个 prompt token，截断了有用的任务上下文。将 vLLM 提高到 `max_model_len=1280` 和 `prompt_token_budget=1024`，并为 merged checkpoint 使用 tokenizer 兼容副本后，在 256 样本检查上把 schema 有效率从约 60% 恢复到 97.66%。它也比当前 Transformers 默认值更快：摊销 0.1712s 对比 0.2638s。

vLLM 剩下的问题是质量，而不仅是 schema。在同一个 256 样本 heldout 切片上，最佳 vLLM context1280 运行的命令重合度是 `0.0993`，而 Transformers batch32 排序默认值是 `0.1445`。严格结构化 JSON 在 128 样本检查上只把 schema 提高到 98.44%，并把命令重合度降到 `0.0926`，因此仅靠 constrained decoding 还不够。

SGLang 0.5.8 现在已确认是在这台主机上 CUDA 兼容的 serving 路线，前提是安装在 `AgentOptiSGLang058` 中并使用 `torch 2.9.1+cu128`。最新的 SGLang 0.5.14 路线在当前驱动上不可用，因为它安装 `torch 2.11.0+cu130`，而主机驱动是 CUDA 12.8。SGLang 0.5.8 在 GPU1 上通过 `/generate` 服务 merged planner，在 128 样本检查上达到 0.1260s 摊销延迟和 872.10 tok/s，但命令重合度只有 `0.0856`。强制 greedy sampling 改善了 32 样本重合度，但没有在 128 样本上保持住，schema 降到 96.09%，重合度也只有 `0.1013`。

Serving 路线决策表：

| 路线 | 样本数 | Schema 有效 | 命令重合度 | 摊销请求 | Tok/s | 决策 |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Transformers batch32 sorted | 256 | 100.00% | 0.1445 | 0.2173s | 577.51 | 当前高准确率默认 |
| Transformers batch16 sorted | 256 | 100.00% | 0.1399 | 0.2638s | 481.10 | 低显存 fallback |
| Transformers batch64 sorted | 256 | 100.00% | 0.1427 | 0.2244s | 566.87 | 比 batch32 慢 |
| Transformers batch16 seq768 sorted | 256 | 100.00% | 0.1333 | 0.2420s | 519.25 | 速度候选，需要 task eval |
| vLLM context1280 batch16 text prompt | 256 | 97.66% | 0.0993 | 0.1712s | 632.74 | 仅作为速度候选 |
| SGLang 0.5.8 default sampling | 128 | 98.44% | 0.0856 | 0.1260s | 872.10 | 最快，但质量差距过大 |
| SGLang 0.5.8 greedy prompt1024/max224 | 128 | 96.09% | 0.1013 | 0.1280s | 833.54 | 不优于默认 |

当前建议：保留 merged Transformers model，并使用 `batch_size=32`、prompt-length sorting、`max_seq_length=1024`、`max_new_tokens=256`、`bf16` 作为当前高准确率优化路线。使用 batch16 sorted 作为低显存 fallback。只有在 task-level validation 或针对服务栈的 fine-tuning 之后，才把 vLLM context1280 和 SGLang 0.5.8 作为速度优先 serving 候选。它们的吞吐很有潜力，但都还不能保持当前的命令重合质量。

### 发生了什么变化

真正有效的优化不是更多通用 SFT，而是改变 target surface：

```text
old target: verbose <think> text followed by JSON
stage2: JSON-only assistant target
stage3: strict JSON output instruction
stage4: action-level JSON with max 3 commands and shorter analysis/plan fields
stage5: short-command JSON, dropping command keystrokes longer than 160 chars
stage6: compact action2 JSON, dropping command keystrokes longer than 120 chars
```

这让模型停止把大部分 token 预算花在隐藏 reasoning 上，并更早转向 planner action object。

### 下一步方向

现在还不要用这个 checkpoint 替换当前 OpenClaw planner。Stage6 现在是更强的 compact next-actions 策略候选，merged batch32 排序路线在 GPU1 上将摊销请求延迟降到 0.2173s，并在 256 样本检查上保持 100% schema 有效，但在替换 deterministic planner 之前，它仍然需要 runtime integration 和 task-level evaluation。

下一轮优化应该选择以下方向之一：

```text
1. continue stage6 with more compact short-command rows and evaluate at 64+ generation examples each time
2. train or distill against the target serving stack, especially vLLM/SGLang, because decoding-stack differences change command quality even when schema is mostly valid
3. wire the merged Transformers batch32 sorted path into a planner-serving wrapper with schema validation and batch16 fallback
4. distill the stage6 policy into Qwen2.5-1.5B-Instruct or a smaller planner if response speed is the main constraint
5. revisit speculative decoding or SGLang RadixAttention only after the serving-stack quality gap is closed
```

## OpenClaw Planner Benchmarks

主 deterministic benchmark：

```text
run: openclaw_benchmark_runs/20260623T143948Z-main-deterministic
tasks: 88 x 3 repeats
stop_criteria_met: true
```

| 策略 | Success | 平均分 | 平均延迟 | 无效工具 | Hallucinations | Loops | Unsafe Auto-Allow |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| greedy_topk | 5.68% | 0.7528 | 0.2884s | 0 | 0 | 0 | 0 |
| audit_astar | 100.00% | 1.0000 | 0.2829s | 0 | 0 | 0 | 0 |
| audit_reflexion | 100.00% | 1.0000 | 0.2948s | 0 | 0 | 0 | 0 |

No-hint control：

```text
tasks: 34 stripped multi-source planner tasks
enabled: openclaw_benchmark_runs/20260623T143906Z-nohint-model-enabled
disabled: openclaw_benchmark_runs/20260623T143906Z-nohint-model-disabled
profileguard: openclaw_benchmark_runs/20260627T-stage7-profileguard-nohint-enabled
```

| 条件 | Success | Holdout Success | 平均分 | 平均延迟 | 安全回退 |
| --- | ---: | ---: | ---: | ---: | ---: |
| learned profile model disabled | 5.88% | 0.00% | 0.7917 | 0.3766s | 0 |
| learned profile model enabled | 97.06% | 100.00% | 0.9902 | 0.2904s | 0 |
| high-confidence skill profile guard | 100.00% | 100.00% | 1.0000 | 0.3065s | 0 |

最新一轮把 no-hint 剩下的失败定位到 `general_skillsbench_007_drone-planning-control`：profile model 已经以 1.0 置信度预测 `skill_workflow -> file_writer,command_runner`，但 runtime 的 local-project guard 把 learned tools 拦掉了。现在只允许高置信 `skill_workflow` 穿透这个 guard，同时保留显式只读保护。重跑 34 题 no-hint 后，`audit_astar` 达到 100.00% success、100.00% holdout success，并且 invalid tools、hallucinations、loops、unsafe auto-allow 都保持 0。

现有 OpenClaw planner 路线仍然健康。新的 LoRA planner checkpoint 与该 runtime 分离：Stage7 在 command/action JSON 的 1k heldout 上更好，但 OpenClaw task-level benchmark 当前仍应该走 profile-aware `LocalAuditPlanner`，直到完成直接的本地 HF planner adapter。

## Stage8 偏好优化探索

这一轮基于 DPO 做了真正实验，而不是只停留在路线讨论。依据来自 DPO、AgentPRM、Agent Lightning、LATS/Reflexion 等工作：如果已经有 `chosen/rejected`，可以尝试直接偏好优化；但 agent 场景里的动作好坏往往不是单一二分类，所以 pair 质量会决定成败。

新增脚本：

```text
scripts/train_planner_dpo.py
scripts/filter_preference_pairs.py
```

偏好数据诊断：

```text
combined stage7 pairs: 632
score_delta < 0: 288
risk_delta > 0: 86
strict filter: overlap_delta >= 0.10, score_delta >= 0, risk_delta <= 0
strict output rows: 186
```

同一 heldout 512 切片、同一 Transformers batch32 serving profile：

| 模型 | 路线 | Schema | Command overlap | 摊销请求 | Long cmd | Script-like | Validation-only | 决策 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| stage6 baseline | SFT | 100.00% | 0.2127 | 0.2286s | 2.34% | 3.52% | 8.98% | 旧 baseline |
| stage7 verifier 500 | verifier SFT | 100.00% | 0.2223 | 0.2098s | 2.15% | 3.12% | 4.30% | 继续保留最佳候选 |
| stage8 DPO-100 | 全 632 pair DPO | 100.00% | 0.2029 | 0.2162s | 0.98% | 1.76% | 3.12% | 不提升，拒绝 |
| stage8b strict DPO-60 | 186 strict pair DPO | 100.00% | 0.2126 | 0.2136s | 2.34% | 3.52% | 6.05% | 不提升，拒绝 |

结论：DPO 路线本身是可运行的，GPU1 smoke、100-step 和 strict-pair 训练都完成了；但当前 pair 构造不够干净，直接 DPO 会牺牲 command relevance。下一轮不应该继续盲目加 DPO step，而应该先做 PRM/process-reward 风格的数据构造，把“命令相关性、风险、安全、进度”分开打分，再生成更一致的偏好对。

## Stage9/Stage10 创新优化探索

这一轮围绕“不要只调 batch/token，而是把 planner 失败机制做成可训练、可路由、可否决的策略”继续迭代。新增方向包括：

```text
1. PRM/process-reward pair mining：把 relevance、progress、safety、efficiency 分开打分再构造偏好对
2. low-progress failure label：识别 python --version / pwd / which 这类不推进任务的探测动作
3. failure-focused micro-SFT：只用明确失败输出 + 干净 target 做小步纠偏
4. final-state postprocess guard：尝试将 task_complete=true 的最终检查命令折叠为空命令
5. dual-model risk-type routing：Stage7 为主，只在 long/script/multiline 结构风险样本上调用 Stage9 第二候选
```

新增脚本：

```text
scripts/build_stage9_prm_pairs.py
scripts/build_failure_repair_sft.py
scripts/benchmark_generation_postprocess.py
scripts/planner_route_policy.py
scripts/benchmark_transformers_route_planner.py
```

Stage9 PRM 数据构造：

| 数据 | Rows | 选择逻辑 |
| --- | ---: | --- |
| `stage9_prm_pairs_initial1k_margin8_20260628.jsonl` | 406 | fast/medium/rerank 多候选 process reward margin |
| `stage9_prm_pairs_expand2k_margin8_20260628.jsonl` | 827 | 追加 2k candidate pool |
| `stage9_prm_pairs_combined3k_margin8_20260628.jsonl` | 1073 | 去重后的 DPO pair |
| `stage9_prm_sft_combined3k_margin8_20260628.jsonl` | 1072 | 去重后的 chosen SFT rows |

Stage9 PRM-DPO 训练：

```text
model: models/20260628T-stage9-prm-dpo-100-merged
base: models/20260625T002525Z-qwen25-3b-stage6-merged
adapter init: models/20260627T-stage7-verifier-combined3k-500/final_adapter
train pairs: 1073
steps: 100
```

同一 heldout 512 切片：

| 模型/路线 | Schema | Overlap | 摊销请求 | Long cmd | Script-like | Validation-only | Retry | 决策 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| stage7 verifier 500 | 100.00% | 0.2223 | 0.2098s | 2.15% | 3.12% | 4.30% | 2 | 当前最佳单模型 |
| stage9 PRM-DPO-100 | 100.00% | 0.2205 | 0.2159s | 1.76% | 3.32% | 5.47% | 3 | 不替换 stage7；可作风险候选 |
| stage10 progress prompt | 100.00% | 0.2026 | 0.2305s | 1.17% | 2.15% | 4.10% | 3 | 拒绝：提示注入伤相关性 |
| stage10 strict repair SFT | 99.80% | 0.1973 | 0.2013s | 0.78% | 0.98% | 2.54% | 1 | 拒绝：安全更好但语义明显退化 |
| stage10 final-check postprocess | 100.00% | 0.2043 | 0.2086s | 2.15% | 3.12% | 4.30% | n/a | 拒绝：清空最终检查命令伤 overlap |
| stage10 dual route budget8 | 100.00% | 0.2228 | 0.2265s est. | 1.17% | 2.15% | 3.71% | n/a | 实验候选：风险下降，延迟 +8.6% |

同一 heldout 1k 切片：

| 模型/路线 | Schema | Overlap | 摊销请求 | Long cmd | Script-like | Validation-only | 决策 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| stage7 verifier 500 | 100.00% | 0.2294 | 0.2048s | 1.70% | 2.20% | 4.10% | 当前最佳单模型 |
| stage9 PRM-DPO-100 | 100.00% | 0.2241 | 0.2084s | 1.20% | 2.30% | 4.70% | 不替换 stage7 |
| stage10 dual route budget8 | 100.00% | 0.2295 | 0.2223s est. | 0.80% | 1.40% | 3.40% | 实验候选：+0.0001 overlap，风险下降，延迟 +8.6% |
| stage10 dual route threshold16 offline | 100.00% | 0.2298 | 0.2180s est. | 0.80% | 1.40% | 3.40% | 离线看好，但被真实在线验证取代 |
| stage10 dual route threshold16 online | 100.00% | 0.2287 | 0.2429s | 1.30% | 1.70% | 3.60% | 拒绝：风险下降但 overlap 回退、延迟偏高 |
| stage10 long/script-only margin12 online | 100.00% | 0.2296 | 0.2330s | 1.10% | 1.70% | 4.10% | 改善触发范围，但延迟仍接近门槛 |
| stage10 long/script-only margin12 sec176 online | 100.00% | 0.2301 | 0.2334s | 0.80% | 1.40% | 4.10% | 偏安全变体：long/multiline 略低但稍慢 |
| stage10 long/script-only margin12 sec168 online | 100.00% | 0.2301 | 0.2323s | 0.90% | 1.40% | 4.10% | 被 blockcomplete 取代；保留为偏安全变体 |
| stage10 long/script-only margin12 sec168 blockcomplete online | 100.00% | 0.2303 | 0.2199s | 1.00% | 1.50% | 4.10% | quality-best：真实在线 +0.0009 overlap，延迟约 +6.6% |
| stage10 long/script-only margin12 sec168 blockcomplete suppressany online | 100.00% | 0.2302 | 0.2178s | 1.20% | 1.70% | 4.10% | fast-balanced：Stage9 请求 1.80%，延迟约 +5.7% |
| stage10 long/script-only margin12 sec168 blockcomplete suppresscomplete online | 100.00% | 0.2301 | 0.2173s | 0.90% | 1.60% | 4.10% | speed/safety：最快且 long/multiline 最低，overlap 略低 |

结论：

```text
Stage7 仍然是最佳单模型 planner checkpoint。
Stage9 说明 PRM-style 数据确实比 Stage8 DPO 稳，但直接 DPO 仍不足以超过 Stage7。
把 failure memory 写进推理 prompt、micro-SFT、粗暴 postprocess 都被 heldout 指标否决。
当前唯一可保留的新路线是 Stage7 主模型 + Stage9 风险类型条件化双候选。原始 threshold16 离线结果看起来更好，但真实在线验证显示 validation-only 样本会拉低 Stage9 相关性，且实际二候选成本高于估算。新版本只对 long/script/multiline 结构风险触发 Stage9，并把 secondary 生成预算继续压到 168 tokens；随后增加 `complete_with_commands` blocklist，阻止 Stage9 把“任务完成”与“继续执行命令”混在一起覆盖 Stage7。当前不是单点最优，而是 Pareto：`sec168_blockcomplete` 是 quality-best，overlap 0.2303；`sec168_blockcomplete_suppressany` 是 fast-balanced，Stage9 请求率降到 1.80%，overlap 0.2302，延迟约 +5.7%；`sec168_blockcomplete_suppresscomplete` 是 speed/safety，overlap 0.2301，但 long/multiline 风险最低且最快。默认单模型仍是 Stage7。
```

## Stage11 DeepSpec/DSpark Speculative Decoding 探索

用户补充的配套项目是 `deepseek-ai/DeepSpec`。官方 README 把它定义为 draft model 训练和 speculative decoding 评估代码库，支持 DSpark、DFlash、Eagle3；但默认 `Qwen/Qwen3-4B` 数据准备会构建 target cache，并提示约 38 TB 存储，默认脚本也按 8 张 GPU 设计。因此本轮没有把 DeepSpec 默认训练管线直接塞进 AgentOpti，而是先做最小可复现实验：用已有 1k heldout 生成结果比较 Stage7 target 与候选 draft 的 token agreement，判断 planner 输出是否值得训练专用小 drafter。

新增脚本与配置：

```text
scripts/benchmark_speculative_acceptance.py
configs/stage11_deepspec_acceptance_probe.json
eval_runs/20260629T-stage11-deepspec-acceptance-stage6draft-stage7target-1k
eval_runs/20260629T-stage11-deepspec-acceptance-stage9draft-stage7target-1k
eval_runs/20260629T-stage11-deepspec-acceptance-stage7self-sanity-1k
```

同一 heldout 1k，target 固定为 Stage7：

| Draft 候选 | Draft overlap | Exact text | 平均前缀匹配 | Aligned token match | Block=8 理论 target-step 上限 | 结论 |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Stage6 same-size proxy | 0.2144 | 0.00% | 8.13% | 12.46% | 1.79x | 拒绝直接作为 draft：同尺寸且 agreement 太低 |
| Stage9 same-size near-draft proxy | 0.2241 | 34.00% | 58.11% | 64.81% | 5.89x | 证明 Stage7 输出可预测，但同尺寸不能真正加速 |
| Stage7 self sanity | 0.2294 | 100.00% | 100.00% | 100.00% | 8.79x | sanity 通过，pairing/tokenizer 比较有效 |

解释：

```text
DeepSpec/DSpark 可以用，但不是“直接拉默认管线就训练”的路线。
Stage6 作为 draft 的 token agreement 太低，且模型大小和 Stage7 一样，不会带来实际 serving 加速。
Stage9 与 Stage7 输出高度接近，说明 planner JSON 输出空间确实适合 speculative decoding；但 Stage9 仍是同尺寸模型，只能作为可预测性证据，不能作为最终高速 draft。
下一步如果继续 Stage11，应训练或蒸馏一个 planner-specific 小 drafter，目标是保留 Stage7 schema/overlap，同时在真实在线 1k 上让延迟相对 Stage7 降低至少 8%-15%。晋级证据必须是真实 online speculative benchmark，而不是仅靠 offline acceptance proxy。
```

## Stage11 DeepSpec 深度融合实现进展

在确认 DeepSpec 默认 Qwen3/Gemma4 路线与当前 Stage7 的 Qwen2 架构不完全兼容后，本轮没有停在“可以参考”的层面，而是把项目源码接入到 `Agent_Planner` 的 ignored 实验树，并补齐 OpenClaw 专用适配层。

新增/复用产物：

```text
external/DeepSpec
deepspec_openclaw/modeling/dspark/qwen2/config.py
deepspec_openclaw/modeling/dspark/qwen2/modeling.py
deepspec_openclaw/trainer/qwen2_dspark_trainer.py
scripts/build_deepspec_planner_cache.py
configs/stage11_dspark_qwen2_planner_smoke.py
DEEPSPEC_FUSION_PLAN_CN.md
```

关键工程决策：

```text
1. 直接复用 DeepSpec 的 target_cache_dataset、BaseTrainer、DSpark loss、Markov/confidence utilities。
2. 从官方 Qwen3DSparkModel 机械 port 出 Qwen2DSparkModel，匹配当前 Stage7/Stage9 的 Qwen2ForCausalLM。
3. 不走 DeepSpec 默认 qwen chat parser；新增 planner direct SFT cache builder，直接保留 OpenClaw SFT text 和 assistant JSON loss mask。
4. 不安装 DeepSpec 全量 requirements，只补最小运行依赖 tensorboard/prettytable，避免破坏现有 torch/transformers/GPU 环境。
```

已验证：

| 验证项 | 结果 |
| --- | --- |
| Qwen2DSparkModel 实例化 | 通过：`Qwen2DSparkModel 3 [12] 1 151666` |
| 1k cache 预算估算 | 通过：`max_length=384, layers=[12,24]` 约 4.1093 GiB |
| 8 样本 GPU1 target cache | 通过：`eval_runs/20260629T-stage11-deepspec-cache-smoke8-l384-layer12-24/target_cache` |
| DeepSpec trainer 1-step | 通过：loss 4.3045，checkpoint 写入 `models/openclaw_agent_planner/stage11_dspark_qwen2_planner_smoke/step_1` |

当前 Stage11 深度融合链路已经通了：

```text
OpenClaw planner SFT text
  -> planner direct target cache
  -> DeepSpec CacheDataset/BaseTrainer/loss
  -> Qwen2DSparkModel
  -> DSpark draft checkpoint
```

下一步不能直接拿这个 1-step checkpoint 评估质量；它只是链路 smoke。真正优化要补 planner greedy exact speculative evaluator：draft 用 argmax proposal，target Stage7 做 exact verify，保证输出尽量等价于 Stage7 greedy，再进入 128/1k latency 与 overlap 对比。

### Stage11 128x20 DSpark 短训与 speculative benchmark

在 1-step smoke 之后，继续做了一轮可复现实验，目的不是晋级，而是验证 DeepSpec draft 训练后 acceptance 是否能起跳。

新增产物：

```text
scripts/benchmark_dspark_speculative_planner.py
eval_runs/20260629T-stage11-deepspec-cache-train128-l384-layer12-24
models/openclaw_agent_planner/stage11_dspark_qwen2_planner_128x20/step_20
eval_runs/20260629T-stage11-dspark-speculative-128x20-heldout5001-8
eval_runs/20260629T-stage11-stage7-baseline-heldout5001-8-max128-batch1
eval_runs/20260629T-stage11-dspark-speculative-128x20-trainline1-4
eval_runs/20260629T-stage11-dspark-speculative-128x20-trainline1-4-seq384
eval_runs/20260630T-stage11-targetonly-loop-heldout5001-8-eager
eval_runs/20260630T-stage11-dspark-speculative-128x20-heldout5001-8-eager
eval_runs/20260630T-stage11-dspark-speculative-128x20-heldout5001-8-seqverify
eval_runs/20260630T-stage11-dspark-speculative-128x20-heldout5001-8-seqverify-margin5
```

关键结果：

| 实验 | 样本 | Schema | Overlap | Mean request | Verify rate | Acceptance | 决策 |
| --- | ---: | ---: | ---: | ---: | ---: | --- | --- |
| Stage7 baseline batch1 max128 | heldout5001 8 | 87.50% | 0.0754 | 1.9151s | n/a | n/a | 同口径参照 |
| DSpark 128x20 max128 | heldout5001 8 | 50.00% | 0.0837 | 2.6567s | 0.1337 | pos0 6.94%，其余 0 | 拒绝晋级 |
| DSpark 128x20 max128 | train line1 4 | 50.00% | 0.1538 | 2.5777s | 0.1340 | pos0 7.17%，其余 0 | 训练切片也不足 |
| DSpark 128x20 max128 seq384 | train line1 4 | 75.00% | 0.1538 | 2.6060s | 0.1331 | pos0 6.48%，其余 0 | 长度对齐未解决 acceptance |

20260630 继续修 evaluator 后新增对照：

| 实验 | 样本 | Schema | Overlap | Mean request | Verify rate | Acceptance / Exact | 决策 |
| --- | ---: | ---: | ---: | ---: | ---: | --- | --- |
| Target-only eager loop | heldout5001 8 | 100.00% | 0.1060 | 2.7194s | 1.0000 | HF greedy exact 87.50% | 诊断上限 |
| DSpark block verify eager | heldout5001 8 | 100.00% | 0.1060 | 2.7484s | 0.1320 | pos0 5.61%，HF exact 37.50% | block verify 不可晋级 |
| DSpark sequential verify eager | heldout5001 8 | 100.00% | 0.1060 | 2.7956s | 0.1316 | pos0 5.29%，其余 0，HF exact 87.50% | 可靠诊断口径 |
| DSpark sequential verify margin5 | heldout5001 8 | 100.00% | 0.1060 | 2.7602s | 0.1308 | pos0 4.63%，其余 0，HF exact 87.50% | margin 未解决低 acceptance |

解释：

```text
128 样本 cache 生成成功，大小约 544M，manifest 估算 0.5312 GiB。
20 step 短训成功，loss 从 4.2659 降到 3.0584，checkpoint 约 3.8G。
但 draft 首位 acceptance 只有约 6%-7%，后续 block 位置为 0，verify_rate 只有约 0.133。
这意味着当前 speculative loop 基本退化成 Stage7 单 token verify，还额外承担 draft 计算成本，因此比 Stage7 batch1 baseline 慢。
20260630 已修复一批 evaluator 问题：读取 Stage7 `generation_config` 里的 `repetition_penalty=1.05`，target prefill 显式传入 attention/cache，新增 4D causal block mask、`--verify-mode sequential` 与 `--accept-margin`。
其中 target-only eager loop 已达到 8 条 exact 87.50%，剩余不一致集中在近似 tie 的 token 边界；block verify 的 exact 只有 37.50%，说明 Qwen2 block target forward 仍不能作为 correctness 口径。
sequential verify 与 target-only exact 对齐，因此它是下一轮 DeepSpec 诊断的默认模式。
```

当前结论：

```text
DeepSpec/DSpark 的源码级融合已经成立，cache/trainer/checkpoint/evaluator 都能在 GPU1 上跑通。
但当前 2-layer、128 样本、20 step draft 不能作为 serving 加速方案。
下一步不直接扩大 10k 训练；先用 sequential verify 跑 1k diagnostic，只有 acceptance 明显提升且 schema/overlap 不回退时，再做 1k cache 和更强 draft/layer 配置。
block verify 只能在与 sequential/HF 等价后作为 speed probe。
```

### Stage11 训练步数与 draft 容量对照

在 evaluator 修复后继续做了三组小成本对照：4-layer draft、2-layer 100 step、2-layer 200 step。目的不是晋级，而是判断当前瓶颈是 draft 容量、训练步数，还是 DSpark 结构本身。

新增产物：

```text
models/openclaw_agent_planner/stage11_dspark_qwen2_planner_128x20_d4/step_20
models/openclaw_agent_planner/stage11_dspark_qwen2_planner_128x100/step_100
models/openclaw_agent_planner/stage11_dspark_qwen2_planner_128x200/step_200
eval_runs/20260630T-stage11-dspark-seqverify-heldout5001-16-calib
eval_runs/20260630T-stage11-dspark-d4-seqverify-heldout5001-16
eval_runs/20260630T-stage11-dspark-128x100-seqverify-heldout5001-16
eval_runs/20260630T-stage11-dspark-128x200-seqverify-heldout5001-16
eval_runs/20260630T-stage11-dspark-128x200-seqverify-heldout5001-64
```

同一 heldout5001 起点、`max_new_tokens=128`、`attn_implementation=eager`、`verify-mode=sequential`：

| Draft | 样本 | Schema | Overlap | Mean request | Verify rate | Acceptance by position | Exact |
| --- | ---: | ---: | ---: | ---: | ---: | --- | ---: |
| 128x20 d2 | 16 | 75.00% | 0.1106 | 2.7097s | 0.1320 | `[5.62%, 0, 0, 0, 0, 0, 0]` | 87.50% |
| 128x20 d4 | 16 | 75.00% | 0.1106 | 2.8588s | 0.1320 | `[5.62%, 0, 0, 0, 0, 0, 0]` | 87.50% |
| 128x100 d2 | 16 | 75.00% | 0.1106 | 2.6625s | 0.1698 | `[31.25%, 4.27%, 0.34%, 0, 0, 0, 0]` | 87.50% |
| 128x200 d2 | 16 | 75.00% | 0.1106 | 2.5871s | 0.2280 | `[41.93%, 15.05%, 8.85%, 6.73%, 4.90%, 3.34%, 2.04%]` | 87.50% |
| 128x200 d2 | 64 | 68.75% | 0.1377 | 2.5221s | 0.2313 | `[44.34%, 15.42%, 8.90%, 6.47%, 4.66%, 3.27%, 2.36%]` | 78.12% |

结论：

```text
4-layer 不带来 acceptance 增益，反而更慢，先否掉。
训练步数是有效变量：20 -> 100 -> 200 step 持续提高 acceptance 和 verify_rate。
128x200 是当前 Stage11 最好 draft，但还不是 serving 晋级版本；sequential verify 只是 correctness diagnostic，block verify 的等价性仍未修好。
64 条结果稳定，说明下一步可以扩 1k cache，而不是继续在 128 cache 上调小参数。
但当前 Agent_Planner 实验树约 94G，已超过原先 50G 约束；1k `[12,24]` cache 估算 4.1093GiB。扩 1k 前应先清理 rejected/superseded drafts 和旧模型。
```
