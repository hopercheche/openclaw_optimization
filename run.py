import os
from pathlib import Path

from aliyuncs import ALIYUNCS_BASE_URL, get_api_key, get_model_name

root = Path('/home/lenovo/code/AIE4902')
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
    'EVALSCOPE_JUDGE_STRATEGY': 'rule',
})

from openclaw_evalscope_cli.run_evalscope import main
main()