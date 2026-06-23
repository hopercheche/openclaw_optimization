# OpenClaw Planner Model Matrix Report

- Created at: 2026-06-22T03:10:13.868288Z
- Output dir: `/home/litangchao/OpenClawPOpti/data/model_matrix/20260622T030951Z`
- Config path: `/home/litangchao/OpenClawPOpti/benchmarks/model_matrix.example.json`
- Task count: 24
- Repeat count: 1
- Split filter: holdout
- Strategies: greedy_topk, audit_astar

## Matrix Summary

| Entry | Runtime | Model ready | Missing env | Stop criteria | `audit_astar` success | `greedy_topk` success | Model fallback rate | Model skip rate |
| --- | --- | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| `deterministic_baseline` | deterministic | False | - | False | 100.00% | 33.33% | 0.00% | 100.00% |
| `as2_deepseek_flash` | as2 | False | DEEPSEEK_API_KEY | False | 100.00% | 33.33% | 0.00% | 100.00% |
| `as2_openai_compatible` | as2 | False | OPENAI_API_KEY | False | 100.00% | 33.33% | 0.00% | 100.00% |
| `as2_dashscope_qwen` | as2 | False | DASHSCOPE_API_KEY | False | 100.00% | 33.33% | 0.00% | 100.00% |

## Entry Details

### deterministic_baseline

- Output dir: `/home/litangchao/OpenClawPOpti/data/model_matrix/20260622T030951Z/deterministic_baseline`
- Runtime: deterministic
- Required env present: True
- Missing required env: []
- Env override keys: []
- AS2 status: model_ready=False, provider=None, model=None
- Model metrics: {'runs': 18, 'model_started_count': 0, 'model_result_count': 0, 'model_fallback_count': 0, 'model_skipped_count': 18, 'model_success_rate': 0, 'model_fallback_rate': 0, 'model_skip_rate': 1.0}
- Stop criteria met: False

### as2_deepseek_flash

- Output dir: `/home/litangchao/OpenClawPOpti/data/model_matrix/20260622T030951Z/as2_deepseek_flash`
- Runtime: as2
- Required env present: False
- Missing required env: ['DEEPSEEK_API_KEY']
- Env override keys: ['DEEPSEEK_BASE_URL', 'OPENCLAW_DEEPSEEK_MODEL']
- AS2 status: model_ready=False, provider=None, model=gpt-4.1-mini
- Model metrics: {'runs': 18, 'model_started_count': 0, 'model_result_count': 0, 'model_fallback_count': 0, 'model_skipped_count': 18, 'model_success_rate': 0, 'model_fallback_rate': 0, 'model_skip_rate': 1.0}
- Stop criteria met: False

### as2_openai_compatible

- Output dir: `/home/litangchao/OpenClawPOpti/data/model_matrix/20260622T030951Z/as2_openai_compatible`
- Runtime: as2
- Required env present: False
- Missing required env: ['OPENAI_API_KEY']
- Env override keys: ['OPENAI_BASE_URL', 'OPENCLAW_OPENAI_MODEL']
- AS2 status: model_ready=False, provider=None, model=gpt-4.1-mini
- Model metrics: {'runs': 18, 'model_started_count': 0, 'model_result_count': 0, 'model_fallback_count': 0, 'model_skipped_count': 18, 'model_success_rate': 0, 'model_fallback_rate': 0, 'model_skip_rate': 1.0}
- Stop criteria met: False

### as2_dashscope_qwen

- Output dir: `/home/litangchao/OpenClawPOpti/data/model_matrix/20260622T030951Z/as2_dashscope_qwen`
- Runtime: as2
- Required env present: False
- Missing required env: ['DASHSCOPE_API_KEY']
- Env override keys: ['DASHSCOPE_BASE_URL', 'OPENCLAW_DASHSCOPE_MODEL']
- AS2 status: model_ready=False, provider=None, model=gpt-4.1-mini
- Model metrics: {'runs': 18, 'model_started_count': 0, 'model_result_count': 0, 'model_fallback_count': 0, 'model_skipped_count': 18, 'model_success_rate': 0, 'model_fallback_rate': 0, 'model_skip_rate': 1.0}
- Stop criteria met: False
