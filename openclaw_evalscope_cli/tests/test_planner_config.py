import json
from pathlib import Path

import pytest
from evalscope.config import parse_task_config

from openclaw_evalscope_cli.run_evalscope import build_task_config


def _clear_plugin_env(monkeypatch):
    for name in (
        "OPENCLAW_ROUTER_ENABLED",
        "OPENCLAW_CONTEXT_INDEX_ENABLED",
        "OPENCLAW_PLANNER_ENABLED",
        "OPENCLAW_PLANNER_CONFIG",
        "OPENCLAW_COMPOSE_FILES",
        "OPENCLAW_COMPOSE_PROJECT",
        "OPENCLAW_EVAL_STATE_DIR",
        "OPENCLAW_EVAL_SECRET_DIR",
        "EVALSCOPE_BATCH_SIZE",
    ):
        monkeypatch.delenv(name, raising=False)


def test_planner_config_uses_single_gateway_and_isolated_state(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    _clear_plugin_env(monkeypatch)
    plugin_config = {
        "enabled": True,
        "pythonBin": "python3",
        "timeoutMs": 1800,
        "maxPromptChars": 10000,
    }
    monkeypatch.setenv("OPENCLAW_PLANNER_ENABLED", "true")
    monkeypatch.setenv("OPENCLAW_PLANNER_CONFIG", json.dumps(plugin_config))

    config = build_task_config()
    agent = config["agent_config"]

    assert agent["bridge"]["strict_model_routing"] is False
    assert agent["kwargs"]["router_enabled"] is False
    assert agent["kwargs"]["context_index_enabled"] is False
    assert agent["kwargs"]["planner_enabled"] is True
    assert agent["kwargs"]["planner_config"] == plugin_config
    assert agent["kwargs"]["planner_collect_decision"] is True
    assert agent["kwargs"]["compose_project"] == "openclaw-eval-planner"
    assert len(agent["kwargs"]["compose_files"]) == 1
    assert Path(agent["kwargs"]["compose_files"][0]).name == "docker-compose.evalscope.yml"
    assert Path(config["work_dir"]).parent.name == "outputs"
    assert config["model_id"] == "openclaw_planner_harness"
    parse_task_config(config)


def test_planner_requires_serial_eval(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    _clear_plugin_env(monkeypatch)
    monkeypatch.setenv("OPENCLAW_PLANNER_ENABLED", "true")
    monkeypatch.setenv("EVALSCOPE_BATCH_SIZE", "2")

    with pytest.raises(ValueError, match="Planner v1 requires"):
        build_task_config()
