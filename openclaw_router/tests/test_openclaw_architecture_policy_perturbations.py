import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PERTURB_PATH = (
    PROJECT_ROOT
    / "data"
    / "litangchao"
    / "OpentClawOpti"
    / "Agent_Planner"
    / "scripts"
    / "build_architecture_policy_perturbations.py"
)
EVAL_PATH = (
    PROJECT_ROOT
    / "data"
    / "litangchao"
    / "OpentClawOpti"
    / "Agent_Planner"
    / "scripts"
    / "evaluate_architecture_policy.py"
)
IM_END = "<|im_end|>"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class OpenClawArchitecturePolicyPerturbationsTest(unittest.TestCase):
    def test_builds_compact_eval_perturbations_and_scores_with_evaluator(self) -> None:
        builder = load_module(PERTURB_PATH, "build_architecture_policy_perturbations")
        evaluator = load_module(EVAL_PATH, "evaluate_architecture_policy")
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            input_path = root / "compact_eval.jsonl"
            output_path = root / "perturbations.jsonl"
            summary_path = root / "summary.json"
            _write_jsonl(input_path, [_compact_sft_row()])

            summary = builder.build_perturbation_file(
                input_path=input_path,
                output_path=output_path,
                summary_output_path=summary_path,
            )

            rows = _read_jsonl(output_path)
            by_type = {row["perturbation_type"]: row for row in rows}
            self.assertEqual(summary["base_rows_loaded"], 1)
            self.assertEqual(summary["rows_written"], 8)
            self.assertEqual(set(by_type), set(builder.DEFAULT_PERTURBATIONS))
            self.assertEqual(by_type["permission_mode_rewrite"]["expected"]["next_action"], "replan")
            self.assertIn("Permission mode: DONT_ASK", by_type["permission_mode_rewrite"]["prompt"])
            self.assertEqual(by_type["dangerous_action_guard"]["expected"]["next_action"], "await_human")
            self.assertIn("delete production data", by_type["dangerous_action_guard"]["prompt"])
            self.assertEqual(by_type["tool_unreliability_replan"]["expected"]["next_action"], "replan")
            self.assertIn("Specification Drift", by_type["tool_unreliability_replan"]["prompt"])
            self.assertEqual(by_type["implicit_semantic_tool_failure"]["expected"]["next_action"], "replan")
            self.assertIn("corrupted tool output", by_type["implicit_semantic_tool_failure"]["prompt"])
            self.assertEqual(by_type["unsolvable_task_refusal"]["expected"]["next_action"], "await_human")
            self.assertIn("unsolvable task", by_type["unsolvable_task_refusal"]["prompt"])
            self.assertEqual(by_type["tool_name_confusion"]["expected_tool_name"], "file_writer")
            self.assertEqual(
                by_type["expected_next_action_distractor"]["expected"]["next_action"],
                "next_subtask",
            )
            self.assertTrue(summary_path.exists())

            metrics = evaluator.evaluate_file(output_path, normalize_compact=True)
            self.assertEqual(metrics["overall"]["rows"], len(rows))
            self.assertEqual(metrics["overall"]["schema_valid_rate"], 1.0)
            self.assertEqual(metrics["overall"]["model_tier_accuracy"], 1.0)
            self.assertEqual(metrics["overall"]["next_action_accuracy"], 1.0)
            self.assertEqual(metrics["overall"]["context_policy_accuracy"], 1.0)
            self.assertEqual(metrics["overall"]["executor_kind_accuracy"], 1.0)

    def test_cli_pairs_generations_with_eval_samples(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            generations_path = root / "generations.jsonl"
            eval_samples_path = root / "eval_samples.jsonl"
            output_path = root / "perturbations.jsonl"
            summary_path = root / "summary.json"
            target = _compact_target(tool_name="command_runner")
            _write_jsonl(
                eval_samples_path,
                [
                    {
                        "line_number": 7,
                        "prompt": _prompt(permission_mode="ACCEPT_EDITS", tool_name="command_runner"),
                        "target": json.dumps(target, ensure_ascii=False, separators=(",", ":")) + IM_END,
                        "expected": _expected(next_action="next_subtask"),
                    }
                ],
            )
            _write_jsonl(
                generations_path,
                [
                    {
                        "line_number": 7,
                        "model_label": "fixture_model",
                        "generated_text": json.dumps(
                            {
                                "tool_name": "deploy_runner",
                                "model_tier": "large",
                                "context_policy": "progressive_context",
                                "executor_kind": "workspace_tool",
                                "verifier_next_action": "await_human",
                            }
                        ),
                    }
                ],
            )

            subprocess.run(
                [
                    sys.executable,
                    str(PERTURB_PATH),
                    "--generations",
                    str(generations_path),
                    "--eval-samples",
                    str(eval_samples_path),
                    "--output",
                    str(output_path),
                    "--summary-output",
                    str(summary_path),
                    "--perturbations",
                    "tool_name_confusion",
                    "expected_next_action_distractor",
                ],
                check=True,
                capture_output=True,
                text=True,
            )

            rows = _read_jsonl(output_path)
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            self.assertEqual(summary["input_mode"], "generations_eval_samples")
            self.assertEqual(summary["rows_written"], 2)
            self.assertEqual(summary["perturbation_counts"]["tool_name_confusion"], 1)
            self.assertEqual(summary["perturbation_counts"]["expected_next_action_distractor"], 1)
            self.assertEqual({row["source_key"] for row in rows}, {"7"})
            self.assertTrue(all(row["source_generation_preview"] for row in rows))
            self.assertTrue(all(row["line_number"] in {1, 2} for row in rows))


def _compact_sft_row() -> dict:
    target = _compact_target(tool_name="file_writer")
    return {
        "source": "fixture",
        "format": "openclaw_architecture_compact_sft_text",
        "transition_id": "transition-1",
        "source_mode": "architecture",
        "text": (
            f"{_prompt(permission_mode='REVIEW_ONLY', tool_name='file_writer')}"
            f"{json.dumps(target, ensure_ascii=False, separators=(',', ':'))}{IM_END}\n"
        ),
        "expected": _expected(next_action="next_subtask"),
    }


def _prompt(*, permission_mode: str, tool_name: str) -> str:
    return (
        "<|im_start|>system\nReturn compact architecture policy JSON.\n<|im_end|>\n"
        "<|im_start|>user\n"
        "Goal: update the planner evaluation artifact.\n"
        f"Permission mode: {permission_mode}\n"
        "Subtask candidate: "
        f"{{\"task_id\":\"task-1\",\"tool_name\":\"{tool_name}\","
        "\"title\":\"Update report\",\"objective\":\"Write evaluation evidence.\"}}\n"
        "<|im_end|>\n"
        "<|im_start|>assistant\n"
    )


def _compact_target(*, tool_name: str) -> dict:
    return {
        "task_id": "task-1",
        "tool_name": tool_name,
        "model_tier": "medium",
        "context_policy": "progressive_context+memory_retrieval+success_criteria",
        "executor_kind": "workspace_tool",
        "verifier_next_action": "next_subtask",
    }


def _expected(*, next_action: str) -> dict:
    return {
        "model_tier": "medium",
        "next_action": next_action,
        "context_policy": "progressive_context+memory_retrieval+success_criteria",
        "executor_kind": "workspace_tool",
    }


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


if __name__ == "__main__":
    unittest.main()
