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
    / "build_architecture_adapter_sft.py"
)
IM_END = "<|im_end|>"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class OpenClawArchitectureAdapterSftTest(unittest.TestCase):
    def test_builds_rule_first_round_robin_perturbation_mix(self) -> None:
        builder = load_module(BUILDER_PATH, "build_architecture_adapter_sft")
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            rule_path = root / "rule.jsonl"
            perturb_path = root / "perturb.jsonl"
            output_path = root / "adapter.jsonl"
            summary_path = root / "summary.json"
            _write_jsonl(
                rule_path,
                [
                    _sft_row("rule-1", source="rule", teacher="classifier"),
                    _sft_row("rule-2", source="rule", teacher="classifier"),
                ],
            )
            _write_jsonl(
                perturb_path,
                [
                    _sft_row("a-1", perturbation_type="dangerous_action_guard", next_action="await_human"),
                    _sft_row("a-2", perturbation_type="dangerous_action_guard", next_action="await_human"),
                    _sft_row("b-1", perturbation_type="tool_name_confusion"),
                    _sft_row("c-1", perturbation_type="unsolvable_task_refusal", next_action="await_human"),
                ],
            )

            summary = builder.build_adapter_sft(
                rule_distill_path=rule_path,
                perturbations_path=perturb_path,
                output_path=output_path,
                summary_output_path=summary_path,
                max_rows=5,
                max_rule_rows=2,
            )

            rows = _read_jsonl(output_path)
            self.assertEqual(summary["rows_written"], 5)
            self.assertEqual(summary["source_mix_counts"], {"perturbation": 3, "rule_distillation": 2})
            self.assertEqual([row["source_mix"] for row in rows[:2]], ["rule_distillation", "rule_distillation"])
            self.assertEqual(
                [row["perturbation_type"] for row in rows[2:]],
                ["dangerous_action_guard", "tool_name_confusion", "unsolvable_task_refusal"],
            )
            self.assertEqual([row["line_number"] for row in rows], [1, 2, 3, 4, 5])
            self.assertTrue(all(row["source"] == "openclaw_architecture_adapter_mix" for row in rows))
            self.assertTrue(all(row["source_mode"] == "stage17_architecture_adapter_mix" for row in rows))
            self.assertTrue(all(row["text"].endswith(IM_END + "\n") for row in rows))
            self.assertEqual(rows[0]["adapter_weight"], 1.25)
            self.assertEqual(rows[2]["adapter_weight"], 1.15)
            self.assertTrue(summary_path.exists())


def _sft_row(
    row_id: str,
    *,
    source: str = "perturb",
    teacher: str | None = None,
    perturbation_type: str | None = None,
    next_action: str = "next_subtask",
) -> dict:
    target = {
        "task_id": row_id,
        "tool_name": "command_runner",
        "model_tier": "medium",
        "context_policy": "progressive_context+memory_retrieval+success_criteria",
        "executor_kind": "workspace_tool",
        "verifier_next_action": next_action,
    }
    row = {
        "source": source,
        "format": "openclaw_architecture_compact_sft_text",
        "line_number": 99,
        "transition_id": row_id,
        "tool_name": "command_runner",
        "permission_mode": "ACCEPT_EDITS",
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
    if teacher:
        row["teacher"] = teacher
    if perturbation_type:
        row["perturbation_type"] = perturbation_type
        row["perturbation"] = {
            "type": perturbation_type,
            "expected_changed": next_action != "next_subtask",
        }
    return row


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


if __name__ == "__main__":
    unittest.main()
