import json
from datetime import datetime, timezone
from types import SimpleNamespace

from openclaw_evalscope_cli.experiment_report import generate_experiment_report


class _TaskConfig(SimpleNamespace):
    def to_dict(self):
        return {"datasets": self.datasets}


def test_planner_report_aggregates_task_decisions(tmp_path):
    prediction_dir = tmp_path / "predictions" / "planner-exp"
    prediction_dir.mkdir(parents=True)
    decisions = [
        {
            "schema_version": "1.0",
            "planner_profile": "terminal_cli_workflow",
            "policy_mode": "act",
            "model_tier": "small",
            "primary_executor": "command_runner",
            "next_action": "execute",
            "confidence": {"overall": 0.8, "planner_profile": 0.9},
        },
        {
            "schema_version": "1.0",
            "planner_profile": "policy_tool_agent",
            "policy_mode": "confirm",
            "model_tier": "large",
            "primary_executor": "mcp_tool_runner",
            "next_action": "await_human",
            "confidence": {"overall": 0.6, "planner_profile": 0.7},
        },
    ]
    records = [
        {
            "index": index,
            "model": "planner-exp",
            "model_output": {
                "metadata": {
                    "runner_metrics": {
                        "planner_enabled": True,
                        "planner_decision": decision,
                    },
                },
            },
        }
        for index, decision in enumerate(decisions)
    ]
    (prediction_dir / "acebench_agent.jsonl").write_text(
        "".join(json.dumps(record) + "\n" for record in records),
        encoding="utf-8",
    )

    now = datetime.now(timezone.utc)
    report_path = generate_experiment_report(
        task_config=_TaskConfig(work_dir=str(tmp_path), datasets=["acebench"]),
        status="completed",
        started_at=now,
        finished_at=now,
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    summary = report["openclaw_runtime_metrics"]["planner"]

    assert summary["n_tasks_with_decision"] == 2
    assert summary["decisions_by_profile"] == {
        "policy_tool_agent": 1,
        "terminal_cli_workflow": 1,
    }
    assert summary["decisions_by_policy_mode"] == {"act": 1, "confirm": 1}
    assert summary["decisions_by_model_tier"] == {"large": 1, "small": 1}
    assert summary["decisions_by_primary_executor"] == {
        "command_runner": 1,
        "mcp_tool_runner": 1,
    }
    assert summary["decisions_by_next_action"] == {"await_human": 1, "execute": 1}
    assert summary["mean_confidence"] == 0.7
