import json
import os
from pathlib import Path

from evalscope.config import parse_task_config
from openclaw_evalscope_cli.run_evalscope import build_task_config
from openclaw_evalscope_cli.runner import _parse_prometheus, _prometheus_delta


def _clear_router_env(monkeypatch):
    for name in (
        "OPENCLAW_ROUTER_ENABLED",
        "OPENCLAW_ROUTER_TIERS",
        "EVALSCOPE_ROUTER_MODEL_ROUTES",
        "OPENCLAW_COMPOSE_FILES",
        "OPENCLAW_COMPOSE_PROJECT",
        "OPENCLAW_EVAL_STATE_DIR",
        "OPENCLAW_EVAL_SECRET_DIR",
    ):
        monkeypatch.delenv(name, raising=False)


def test_baseline_config_remains_single_model(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    _clear_router_env(monkeypatch)
    config = build_task_config()

    assert config["agent_config"]["bridge"]["strict_model_routing"] is False
    assert config["agent_config"]["bridge"]["model_routes"] == {}
    assert config["agent_config"]["kwargs"]["router_enabled"] is False
    assert config["agent_config"]["kwargs"]["compose_project"] == "openclaw-eval-baseline"
    assert len(config["agent_config"]["kwargs"]["compose_files"]) == 1


def test_router_config_is_strict_and_uses_isolated_state(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    _clear_router_env(monkeypatch)
    monkeypatch.setenv("OPENCLAW_ROUTER_ENABLED", "true")
    monkeypatch.setenv(
        "OPENCLAW_ROUTER_TIERS",
        json.dumps({"small": "small-model", "mid": "mid-model", "large": "large-model"}),
    )
    routes = {
        name: {
            "model_id": name,
            "eval_type": "mock_llm",
            "openclaw_model": {
                "cost": {"input": 1, "output": 2, "cacheRead": 0.1, "cacheWrite": 1},
            },
        }
        for name in ("small-model", "mid-model", "large-model")
    }
    monkeypatch.setenv("EVALSCOPE_ROUTER_MODEL_ROUTES", json.dumps(routes))

    config = build_task_config()
    agent = config["agent_config"]
    assert agent["bridge"]["strict_model_routing"] is True
    assert set(agent["bridge"]["model_routes"]) == set(routes)
    assert agent["kwargs"]["router_enabled"] is True
    assert agent["kwargs"]["compose_project"] == "openclaw-eval-router"
    assert len(agent["kwargs"]["compose_files"]) == 2
    assert Path(os.environ["OPENCLAW_EVAL_STATE_DIR"]).name == "router-state"
    assert Path(os.environ["OPENCLAW_EVAL_SECRET_DIR"]).name == "router-secrets"
    parsed = parse_task_config(config)
    assert parsed.agent_config.bridge.strict_model_routing is True
    assert set(parsed.agent_config.bridge.model_routes) == set(routes)


def test_prometheus_delta_keeps_only_positive_openclaw_series():
    before = _parse_prometheus(
        'openclaw_model_tokens_total{model="small",token_type="input"} 10\n'
        'ignored_metric 99\n'
    )
    after = _parse_prometheus(
        'openclaw_model_tokens_total{model="small",token_type="input"} 16\n'
        'openclaw_model_cost_usd_total{model="small"} 0.5\n'
    )
    assert _prometheus_delta(before, after) == {
        'openclaw_model_tokens_total{model="small",token_type="input"}': 6.0,
        'openclaw_model_cost_usd_total{model="small"}': 0.5,
    }
