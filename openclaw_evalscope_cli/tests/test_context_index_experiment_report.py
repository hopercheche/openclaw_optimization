import json
from datetime import datetime, timezone
from types import SimpleNamespace

from openclaw_evalscope_cli.experiment_report import generate_experiment_report


class _TaskConfig(SimpleNamespace):
    def to_dict(self):
        return {"datasets": self.datasets}


def test_context_index_report_aggregates_task_audit_metrics(tmp_path):
    prediction_dir = tmp_path / "predictions" / "context-index-exp"
    prediction_dir.mkdir(parents=True)
    records = []
    for index, injected_tokens in enumerate((12, 28)):
        records.append({
            "index": index,
            "model": "context-index-exp",
            "model_output": {
                "metadata": {
                    "runner_metrics": {
                        "context_index_enabled": True,
                        "context_index_audit": {
                            "audit_event_count": 4,
                            "event_counts": {
                                "context_query_created": 1,
                                "context_injected": 2,
                            },
                            "query_count": 1,
                            "candidate_count": 5,
                            "result_count": 2,
                            "retrieved_count": 2,
                            "injected_count": 2,
                            "injected_tokens": injected_tokens,
                            "average_retrieval_score": 0.5 + index * 0.2,
                        },
                    },
                },
            },
        })
    (prediction_dir / "locomo_qa.jsonl").write_text(
        "".join(json.dumps(record) + "\n" for record in records),
        encoding="utf-8",
    )

    now = datetime.now(timezone.utc)
    report_path = generate_experiment_report(
        task_config=_TaskConfig(work_dir=str(tmp_path), datasets=["locomo"]),
        status="completed",
        started_at=now,
        finished_at=now,
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    summary = report["openclaw_runtime_metrics"]["context_index"]

    assert summary["n_tasks_with_audit"] == 2
    assert summary["audit_event_count"] == 8
    assert summary["query_count"] == 2
    assert summary["candidate_count"] == 10
    assert summary["result_count"] == 4
    assert summary["retrieved_count"] == 4
    assert summary["injected_count"] == 4
    assert summary["injected_tokens"] == 40
    assert summary["event_counts"] == {
        "context_injected": 4,
        "context_query_created": 2,
    }
    assert summary["mean_task_retrieval_score"] == 0.6
