from __future__ import annotations

import json
import os
import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from openclaw_evalscope_cli.experiment_report import generate_experiment_report


class _FakeTaskConfig(SimpleNamespace):

    def to_dict(self):
        return self.config


@contextmanager
def _without_price_environment():
    names = [
        "EVALSCOPE_INPUT_PRICE_PER_MILLION",
        "EVALSCOPE_OUTPUT_PRICE_PER_MILLION",
        "EVALSCOPE_CACHED_INPUT_PRICE_PER_MILLION",
        "EVALSCOPE_COST_CURRENCY",
    ]
    previous = {name: os.environ.get(name) for name in names}
    try:
        for name in names:
            os.environ.pop(name, None)
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


class ExperimentReportTest(unittest.TestCase):

    def _make_run(self, root: Path) -> _FakeTaskConfig:
        (root / "reports/model").mkdir(parents=True)
        (root / "predictions/model").mkdir(parents=True)
        (root / "reviews/model").mkdir(parents=True)
        (root / "configs").mkdir()
        (root / "logs").mkdir()

        (root / "reports/model/demo.json").write_text(
            json.dumps({"dataset_name": "demo", "score": 1.0}),
            encoding="utf-8",
        )
        prediction = {
            "index": 0,
            "model": "demo-model",
            "model_output": {
                "model": "demo-model",
                "choices": [{"message": {"content": "answer"}}],
                "metadata": {
                    "task_usage": {
                        "input_tokens": 1000,
                        "output_tokens": 500,
                        "total_tokens": 1500,
                    }
                },
                "time": 2.5,
                "error": None,
            },
        }
        review = {
            "index": 0,
            "target": "answer",
            "sample_score": {
                "sample_id": 7,
                "group_id": 7,
                "sample_metadata": {"question": "demo?"},
                "score": {
                    "value": {"acc": 1.0},
                    "prediction": "answer",
                    "extracted_prediction": "answer",
                    "main_score_name": "acc",
                    "explanation": "matched",
                },
            },
        }
        (root / "predictions/model/demo_main.jsonl").write_text(
            json.dumps(prediction) + "\n",
            encoding="utf-8",
        )
        (root / "reviews/model/demo_main.jsonl").write_text(
            json.dumps(review) + "\n",
            encoding="utf-8",
        )
        (root / "configs/task_config.yaml").write_text("model: demo-model\n", encoding="utf-8")
        (root / "logs/eval_log.log").write_text("done\n", encoding="utf-8")

        return _FakeTaskConfig(
            work_dir=str(root),
            datasets=["demo"],
            config={
                "model": "demo-model",
                "api_key": "top-secret",
                "judge_model_args": {"api_key": "judge-secret", "model_id": "judge"},
            },
        )

    def test_report_contains_config_results_usage_and_cost(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            task_config = self._make_run(root)
            started = datetime(2026, 7, 13, tzinfo=timezone.utc)

            with patch.dict(
                os.environ,
                {
                    "EVALSCOPE_INPUT_PRICE_PER_MILLION": "2",
                    "EVALSCOPE_OUTPUT_PRICE_PER_MILLION": "6",
                    "EVALSCOPE_COST_CURRENCY": "CNY",
                },
            ):
                path = generate_experiment_report(
                    task_config=task_config,
                    status="completed",
                    started_at=started,
                    finished_at=started + timedelta(seconds=3),
                )

            report = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "completed")
            self.assertEqual(report["task_config"]["api_key"], "<redacted>")
            self.assertEqual(report["task_config"]["judge_model_args"]["api_key"], "<redacted>")
            self.assertEqual(report["results"]["dataset_reports"][0]["report"]["score"], 1.0)

            task = report["results"]["task_results"][0]
            self.assertEqual(task["sample_id"], 7)
            self.assertEqual(task["score"], {"acc": 1.0})
            self.assertEqual(task["usage"]["total_tokens"], 1500)
            self.assertEqual(task["cost_estimate"]["total_cost"], 0.005)

            self.assertEqual(report["usage"]["input_tokens"], 1000)
            self.assertEqual(report["usage"]["output_tokens"], 500)
            self.assertEqual(report["cost_estimate"]["status"], "estimated")
            self.assertEqual(report["cost_estimate"]["total_cost"], 0.005)
            self.assertEqual(report["cost_estimate"]["mean_cost_per_task"], 0.005)
            self.assertEqual(report["cost_estimate"]["min_cost_per_task"], 0.005)
            self.assertEqual(report["cost_estimate"]["max_cost_per_task"], 0.005)
            self.assertIn("predictions/model/demo_main.jsonl", report["artifacts"]["predictions"])

    def test_missing_prices_are_reported_as_unavailable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            task_config = self._make_run(root)
            now = datetime.now(timezone.utc)
            with _without_price_environment():
                path = generate_experiment_report(
                    task_config=task_config,
                    status="completed",
                    started_at=now,
                    finished_at=now,
                )

            report = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(report["cost_estimate"]["status"], "unavailable")
            self.assertNotIn("cost_estimate", report["results"]["task_results"][0])
            self.assertEqual(report["usage"]["total_tokens"], 1500)


if __name__ == "__main__":
    unittest.main()
