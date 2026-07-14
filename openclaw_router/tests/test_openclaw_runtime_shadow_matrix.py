import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
AGENT_PLANNER_ROOT = (
    PROJECT_ROOT
    / "data"
    / "litangchao"
    / "OpentClawOpti"
    / "Agent_Planner"
)
MATRIX_PATH = AGENT_PLANNER_ROOT / "scripts" / "benchmark_runtime_shadow_matrix.py"
IM_END = "<|im_end|>"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class OpenClawRuntimeShadowMatrixTest(unittest.TestCase):
    def test_matrix_compares_raw_wrapper_classifier_and_counterfactual(self) -> None:
        matrix = load_module(MATRIX_PATH, "benchmark_runtime_shadow_matrix")
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            raw_path = root / "generations.jsonl"
            reference_path = root / "eval_samples.jsonl"
            output_dir = root / "matrix"

            prompt_1 = (
                "Goal: run tests\nPermission mode: DEFAULT\n"
                "Subtask candidate: {\"task_id\":\"task-1\","
                "\"title\":\"Run validation command\","
                "\"objective\":\"Run a reproducible validation command.\"}\n"
                "<|im_start|>assistant\n"
            )
            prompt_2 = (
                "Goal: plan work\nPermission mode: ACCEPT_EDITS\n"
                "Subtask candidate: {\"task_id\":\"task-2\","
                "\"title\":\"Build bounded plan candidates\","
                "\"objective\":\"Create plan candidates for the next subtask.\"}\n"
                "<|im_start|>assistant\n"
            )
            _write_jsonl(reference_path, [
                reference_row(1, prompt_1, "command_runner", "medium", "await_human", "progressive_context+memory_retrieval+success_criteria", "workspace_tool"),
                reference_row(2, prompt_2, "planner", "small", "next_subtask", "progressive_context+candidate_scores", "read_only_agent"),
            ])
            _write_jsonl(raw_path, [
                raw_row(1, "task-1", "command_runner", "medium", "next_subtask", "progressive_context+memory_retrieval+success_criteria", "workspace_tool"),
                raw_row(2, "task-2", "planner", "small", "next_subtask", "progressive_context+candidate_scores", "read_only_agent"),
            ])

            metrics = matrix.build_shadow_matrix(
                raw_generations=raw_path,
                reference=reference_path,
                eval_samples=reference_path,
                output_dir=output_dir,
            )

            self.assertEqual(metrics["rows_written"], 2)
            self.assertEqual(metrics["predictors"]["raw"]["exact_match_rate"], 0.5)
            self.assertEqual(metrics["predictors"]["wrapped"]["exact_match_rate"], 1.0)
            self.assertEqual(metrics["predictors"]["classifier"]["exact_match_rate"], 1.0)
            self.assertLess(metrics["predictors"]["classifier_no_next_prior"]["exact_match_rate"], 1.0)
            self.assertEqual(metrics["raw_to_wrapped_delta"]["verifier_next_action:repaired"], 1)
            self.assertTrue((output_dir / "shadow_matrix_rows.jsonl").exists())
            self.assertTrue((output_dir / "report.md").exists())


def reference_row(
    line_number: int,
    prompt: str,
    tool_name: str,
    model_tier: str,
    next_action: str,
    context_policy: str,
    executor_kind: str,
) -> dict:
    target = {
        "task_id": f"task-{line_number}",
        "tool_name": tool_name,
        "model_tier": model_tier,
        "context_policy": context_policy,
        "executor_kind": executor_kind,
        "verifier_next_action": next_action,
    }
    return {
        "line_number": line_number,
        "permission_mode": "DEFAULT" if line_number == 1 else "ACCEPT_EDITS",
        "prompt": prompt,
        "expected": {
            "model_tier": model_tier,
            "next_action": next_action,
            "context_policy": context_policy,
            "executor_kind": executor_kind,
        },
        "compact_target": target,
        "target": json.dumps(target, separators=(",", ":")) + IM_END,
        "text": prompt + json.dumps(target, separators=(",", ":")) + IM_END + "\n",
    }


def raw_row(
    line_number: int,
    task_id: str,
    tool_name: str,
    model_tier: str,
    next_action: str,
    context_policy: str,
    executor_kind: str,
) -> dict:
    payload = {
        "architecture": {
            "task_id": task_id,
            "tool_name": tool_name,
            "model_tier": model_tier,
            "context_policy": context_policy,
            "executor_kind": executor_kind,
            "expected_next_action": next_action,
        },
        "verifier": {"next_action": next_action},
    }
    return {
        "line_number": line_number,
        "generated_text": json.dumps(payload, separators=(",", ":")) + IM_END,
    }


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


if __name__ == "__main__":
    unittest.main()
