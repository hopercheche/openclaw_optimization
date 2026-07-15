import json
from pathlib import Path

import pytest
from evalscope.config import parse_task_config

from openclaw_evalscope_cli.run_evalscope import build_task_config
from openclaw_evalscope_cli.runner import _summarize_context_index_audit


def _clear_plugin_env(monkeypatch):
    for name in (
        "OPENCLAW_ROUTER_ENABLED",
        "OPENCLAW_CONTEXT_INDEX_ENABLED",
        "OPENCLAW_CONTEXT_INDEX_CONFIG",
        "OPENCLAW_COMPOSE_FILES",
        "OPENCLAW_COMPOSE_PROJECT",
        "OPENCLAW_EVAL_STATE_DIR",
        "OPENCLAW_EVAL_SECRET_DIR",
        "EVALSCOPE_BATCH_SIZE",
    ):
        monkeypatch.delenv(name, raising=False)


def test_context_index_config_uses_single_gateway_and_isolated_state(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    _clear_plugin_env(monkeypatch)
    plugin_config = {
        "mode": "progressive",
        "recentMessageLimit": 6,
        "retrieval": {"topK": 4, "candidateK": 20, "halfLifeDays": 14},
        "audit": {"enabled": True},
    }
    monkeypatch.setenv("OPENCLAW_CONTEXT_INDEX_ENABLED", "true")
    monkeypatch.setenv("OPENCLAW_CONTEXT_INDEX_CONFIG", json.dumps(plugin_config))

    config = build_task_config()
    agent = config["agent_config"]

    assert agent["bridge"]["strict_model_routing"] is False
    assert agent["kwargs"]["router_enabled"] is False
    assert agent["kwargs"]["context_index_enabled"] is True
    assert agent["kwargs"]["context_index_config"] == plugin_config
    assert agent["kwargs"]["context_index_reset_per_sample"] is True
    assert agent["kwargs"]["compose_project"] == "openclaw-eval-context-index"
    assert len(agent["kwargs"]["compose_files"]) == 1
    assert Path(agent["kwargs"]["compose_files"][0]).name == "docker-compose.evalscope.yml"
    assert Path(config["work_dir"]).parent.name == "outputs"
    parse_task_config(config)


def test_context_index_requires_serial_eval(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    _clear_plugin_env(monkeypatch)
    monkeypatch.setenv("OPENCLAW_CONTEXT_INDEX_ENABLED", "true")
    monkeypatch.setenv("EVALSCOPE_BATCH_SIZE", "2")

    with pytest.raises(ValueError, match="Context Index v1 requires"):
        build_task_config()


def test_context_index_audit_summary_uses_only_new_task_events():
    before = [
        {
            "id": "old",
            "eventType": "context_injected",
            "tokenCount": 999,
            "score": 1.0,
        }
    ]
    after = [
        before[0],
        {
            "id": "query",
            "eventType": "context_query_created",
            "metadata": {"candidateCount": 8, "resultCount": 2},
        },
        {"id": "retrieved-1", "eventType": "context_retrieved", "score": 0.8},
        {"id": "retrieved-2", "eventType": "context_retrieved", "score": 0.4},
        {"id": "injected-1", "eventType": "context_injected", "tokenCount": 21},
        {"id": "injected-2", "eventType": "context_injected", "tokenCount": 13},
        {"id": "filtered", "eventType": "context_filtered", "tokenCount": 7},
    ]

    summary = _summarize_context_index_audit(before, after)

    assert summary["audit_event_count"] == 6
    assert summary["query_count"] == 1
    assert summary["candidate_count"] == 8
    assert summary["result_count"] == 2
    assert summary["retrieved_count"] == 2
    assert summary["injected_count"] == 2
    assert summary["injected_tokens"] == 34
    assert summary["average_retrieval_score"] == pytest.approx(0.6)
    assert summary["event_counts"] == {
        "context_filtered": 1,
        "context_injected": 2,
        "context_query_created": 1,
        "context_retrieved": 2,
    }
