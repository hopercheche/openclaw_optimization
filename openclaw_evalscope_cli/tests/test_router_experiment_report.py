import json
from datetime import datetime, timezone
from types import SimpleNamespace

from openclaw_evalscope_cli.experiment_report import generate_experiment_report


class _TaskConfig(SimpleNamespace):
    def to_dict(self):
        return {"datasets": self.datasets, "api_key": "must-not-leak"}


def test_router_report_contains_per_model_cost_and_runtime_metrics(monkeypatch, tmp_path):
    routes = {
        "small-model": {
            "model_id": "small-model",
            "openclaw_model": {
                "cost": {"input": 1, "output": 2, "cacheRead": 0.1, "cacheWrite": 1},
            },
        },
    }
    monkeypatch.setenv("EVALSCOPE_ROUTER_MODEL_ROUTES", json.dumps(routes))
    monkeypatch.setenv(
        "OPENCLAW_ROUTER_TIERS",
        json.dumps({"small": "small-model", "mid": "mid-model", "large": "large-model"}),
    )

    prediction_dir = tmp_path / "predictions" / "router-exp"
    prediction_dir.mkdir(parents=True)
    record = {
        "index": 0,
        "model": "router-exp",
        "model_output": {
            "model": "router-exp",
            "choices": [{"message": {"content": "answer"}}],
            "metadata": {
                "runner_metrics": {
                    "openclaw_prometheus_delta": {
                        'openclaw_model_call_total{model="small-model"}': 1,
                    },
                },
            },
        },
        "agent_trace": {
            "total_usage": {"input_tokens": 100, "output_tokens": 20},
            "events": [
                {
                    "step": 0,
                    "type": "model_generate",
                    "latency_ms": 50,
                    "payload": {
                        "requested_model": "small-model",
                        "resolved_model": "small-model",
                    },
                    "token_usage": {
                        "input": 100,
                        "output": 20,
                        "cache_read": 10,
                        "cache_write": 5,
                    },
                },
            ],
        },
    }
    (prediction_dir / "gsm8k_main.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")

    now = datetime.now(timezone.utc)
    report_path = generate_experiment_report(
        task_config=_TaskConfig(work_dir=str(tmp_path), datasets=["gsm8k"]),
        status="completed",
        started_at=now,
        finished_at=now,
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))

    assert report["schema_version"] == "1.1"
    assert report["task_config"]["api_key"] == "<redacted>"
    assert report["routing"]["calls_by_tier"] == {"small": 1}
    assert report["cost_estimate"]["source"] == "per_model_bridge_trace"
    assert report["cost_estimate"]["total_cost"] == 0.000136
    assert report["cost_estimate"]["cost_by_model"] == {"small-model": 0.000136}
    assert report["openclaw_runtime_metrics"]["n_tasks_with_metrics"] == 1
    assert report["openclaw_runtime_metrics"]["context_index"]["n_tasks_with_audit"] == 0
    assert report["openclaw_runtime_metrics"]["planner"]["n_tasks_with_decision"] == 0
    task = report["results"]["task_results"][0]
    assert task["model_calls"][0]["requested_model"] == "small-model"
    assert task["cost_estimate"]["total_cost"] == 0.000136
