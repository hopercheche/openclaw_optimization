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
BUILDER_PATH = AGENT_PLANNER_ROOT / "scripts" / "build_architecture_rule_distillation_sft.py"
IM_END = "<|im_end|>"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class OpenClawRuleDistillationSftTest(unittest.TestCase):
    def test_builds_only_raw_mismatch_rows_with_teacher_target(self) -> None:
        builder = load_module(BUILDER_PATH, "build_architecture_rule_distillation_sft")
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            matrix_path = root / "matrix.jsonl"
            samples_path = root / "eval_samples.jsonl"
            output_path = root / "distill.jsonl"

            _write_jsonl(samples_path, [
                {"line_number": 1, "prompt": _prompt("task-1")},
                {"line_number": 2, "prompt": _prompt("task-2")},
            ])
            _write_jsonl(matrix_path, [
                _matrix_row(1, raw_exact=False, next_action="await_human"),
                _matrix_row(2, raw_exact=True, next_action="next_subtask"),
            ])

            summary = builder.build_distillation_file(
                matrix_rows=matrix_path,
                eval_samples=samples_path,
                output_path=output_path,
            )

            rows = [json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(summary["stats"]["rows_written"], 1)
            self.assertEqual(rows[0]["source_key"], 1)
            self.assertIn("wrapper_rules", rows[0])
            self.assertEqual(rows[0]["expected"]["next_action"], "await_human")
            self.assertIn('"verifier_next_action":"await_human"', rows[0]["text"])
            self.assertEqual(rows[0]["teacher"], "classifier")


def _prompt(task_id: str) -> str:
    return (
        "<|im_start|>system\nReturn compact architecture policy JSON.\n<|im_end|>\n"
        "<|im_start|>user\n"
        "Goal: test rule distillation.\n"
        "Permission mode: DEFAULT\n"
        "Subtask candidate: "
        f"{{\"task_id\":\"{task_id}\",\"title\":\"Run validation command\","
        "\"objective\":\"Run validation.\"}}\n"
        "<|im_end|>\n"
        "<|im_start|>assistant\n"
    )


def _matrix_row(key: int, *, raw_exact: bool, next_action: str) -> dict:
    raw_next = next_action if raw_exact else "replan"
    return {
        "line_number": key,
        "key": key,
        "task_id": f"task-{key}",
        "tool_name": "command_runner",
        "permission_mode": "DEFAULT",
        "expected": {
            "model_tier": "medium",
            "verifier_next_action": next_action,
            "context_policy": "progressive_context+memory_retrieval+success_criteria",
            "executor_kind": "workspace_tool",
        },
        "predictions": {
            "raw": _policy(f"task-{key}", raw_next),
            "classifier": _policy(f"task-{key}", next_action),
            "wrapped": _policy(f"task-{key}", next_action),
        },
        "matches": {
            "raw": {
                "model_tier": True,
                "verifier_next_action": raw_exact,
                "context_policy": True,
                "executor_kind": True,
            },
            "classifier": {
                "model_tier": True,
                "verifier_next_action": True,
                "context_policy": True,
                "executor_kind": True,
            },
            "wrapped": {
                "model_tier": True,
                "verifier_next_action": True,
                "context_policy": True,
                "executor_kind": True,
            },
        },
        "exact_match": {
            "raw": raw_exact,
            "classifier": True,
            "wrapped": True,
        },
        "wrapper_rules": ["permission_guard:next_action:DEFAULT"] if not raw_exact else [],
    }


def _policy(task_id: str, next_action: str) -> dict:
    return {
        "task_id": task_id,
        "tool_name": "command_runner",
        "model_tier": "medium",
        "context_policy": "progressive_context+memory_retrieval+success_criteria",
        "executor_kind": "workspace_tool",
        "verifier_next_action": next_action,
    }


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


if __name__ == "__main__":
    unittest.main()
