import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BUILDER_PATH = (
    PROJECT_ROOT
    / "data"
    / "litangchao"
    / "OpentClawOpti"
    / "Agent_Planner"
    / "scripts"
    / "build_architecture_adapter_curriculum.py"
)
IM_END = "<|im_end|>"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class OpenClawArchitectureAdapterCurriculumTest(unittest.TestCase):
    def test_builds_clean_anchored_toolmaze_curriculum(self) -> None:
        builder = load_module(BUILDER_PATH, "build_architecture_adapter_curriculum")
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            clean_path = root / "clean.jsonl"
            adapter_path = root / "adapter.jsonl"
            output_path = root / "curriculum.jsonl"
            summary_path = root / "summary.json"
            _write_jsonl(
                clean_path,
                [
                    _row("clean-next-1", next_action="next_subtask"),
                    _row("clean-next-2", next_action="next_subtask"),
                    _row("clean-await", next_action="await_human"),
                    _row("clean-replan", next_action="replan"),
                ],
            )
            _write_jsonl(
                adapter_path,
                [
                    _row("danger-1", next_action="await_human", perturbation_type="dangerous_action_guard"),
                    _row("tool-1", next_action="next_subtask", perturbation_type="tool_name_confusion"),
                    _row("semantic-1", next_action="replan", perturbation_type="implicit_semantic_tool_failure"),
                ],
            )

            summary = builder.build_curriculum(
                clean_train_path=clean_path,
                adapter_pack_path=adapter_path,
                output_path=output_path,
                summary_output_path=summary_path,
                clean_quotas={"next_subtask": 2, "await_human": 1, "replan": 1},
                adapter_rows=2,
            )

            rows = _read_jsonl(output_path)
            self.assertEqual(summary["rows_written"], 6)
            self.assertEqual(summary["curriculum_mix_counts"], {"clean_anchor": 4, "toolmaze_adapter": 2})
            self.assertEqual([row["curriculum_mix"] for row in rows[:4]], ["clean_anchor"] * 4)
            self.assertEqual([row["curriculum_mix"] for row in rows[4:]], ["toolmaze_adapter"] * 2)
            self.assertEqual(rows[0]["adapter_weight"], 0.9)
            self.assertTrue(all(row["source"] == "openclaw_architecture_adapter_curriculum" for row in rows))
            self.assertTrue(all(row["source_mode"] == "stage18_architecture_adapter_curriculum" for row in rows))
            self.assertTrue(all(row["text"].endswith(IM_END + "\n") for row in rows))
            self.assertTrue(summary_path.exists())


def _row(row_id: str, *, next_action: str, perturbation_type: str | None = None) -> dict:
    target = {
        "task_id": row_id,
        "tool_name": "command_runner",
        "model_tier": "medium",
        "context_policy": "progressive_context+memory_retrieval+success_criteria",
        "executor_kind": "workspace_tool",
        "verifier_next_action": next_action,
    }
    row = {
        "source": "fixture",
        "format": "openclaw_architecture_compact_sft_text",
        "line_number": 7,
        "transition_id": row_id,
        "expected": {
            "model_tier": "medium",
            "next_action": next_action,
            "context_policy": "progressive_context+memory_retrieval+success_criteria",
            "executor_kind": "workspace_tool",
        },
        "text": (
            "<|im_start|>system\nReturn JSON.\n<|im_end|>\n"
            f"<|im_start|>user\nTask {row_id}\n<|im_end|>\n"
            "<|im_start|>assistant\n"
            f"{json.dumps(target, ensure_ascii=False, separators=(',', ':'))}{IM_END}\n"
        ),
    }
    if perturbation_type:
        row["perturbation_type"] = perturbation_type
        row["perturbation"] = {"type": perturbation_type, "expected_changed": next_action != "next_subtask"}
    return row


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


if __name__ == "__main__":
    unittest.main()
