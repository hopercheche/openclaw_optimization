import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EVAL_PATH = (
    PROJECT_ROOT
    / "data"
    / "litangchao"
    / "OpentClawOpti"
    / "Agent_Planner"
    / "scripts"
    / "evaluate_architecture_policy.py"
)


class OpenClawArchitecturePolicyEvalTest(unittest.TestCase):
    def test_cli_scores_schema_and_grouped_policy_accuracy(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture = root / "fixture.jsonl"
            output_dir = root / "eval"
            _write_jsonl(
                fixture,
                [
                    _sft_row(
                        transition_id="t1",
                        source_mode="architecture",
                        stratum="architecture|tier=small|next=next_subtask",
                        labels={
                            "model_tier": "small",
                            "next_action": "next_subtask",
                            "context_policy": "progressive_context",
                            "executor_kind": "policy_gate",
                        },
                        target=_target(
                            model_tier="small",
                            next_action="next_subtask",
                            context_policy="progressive_context",
                            executor_kind="policy_gate",
                        ),
                    ),
                    _sft_row(
                        transition_id="t2",
                        source_mode="legacy",
                        stratum="legacy|tier=medium|next=await_human",
                        labels={
                            "model_tier": "medium",
                            "next_action": "await_human",
                            "context_policy": "legacy_event_replay",
                            "executor_kind": "legacy_tool",
                        },
                        target=_target(
                            model_tier="large",
                            next_action="replan",
                            context_policy="missing_context",
                            executor_kind="legacy_tool",
                        ),
                    ),
                    {
                        "transition_id": "t3",
                        "source_mode": "legacy",
                        "balance_stratum": "legacy|tier=small|next=next_subtask",
                        "model_tier": "small",
                        "next_action": "next_subtask",
                        "labels": {
                            "context_policy": "legacy_event_replay",
                            "executor_kind": "legacy_tool",
                        },
                        "text": (
                            "<|im_start|>system\nReturn JSON.\n<|im_end|>\n"
                            "<|im_start|>user\nGoal: broken.\n<|im_end|>\n"
                            "<|im_start|>assistant\n{not-json<|im_end|>\n"
                        ),
                    },
                ],
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(EVAL_PATH),
                    "--input",
                    str(fixture),
                    "--output-dir",
                    str(output_dir),
                ],
                check=True,
                text=True,
                capture_output=True,
            )

            metrics = json.loads((output_dir / "metrics.json").read_text(encoding="utf-8"))
            self.assertIn("schema_valid_rate", result.stdout)
            self.assertTrue((output_dir / "report.md").exists())
            self.assertEqual(metrics["overall"]["rows"], 3)
            self.assertEqual(metrics["overall"]["schema_valid_count"], 2)
            self.assertEqual(metrics["overall"]["model_tier_correct"], 1)
            self.assertEqual(metrics["overall"]["model_tier_total"], 3)
            self.assertEqual(metrics["overall"]["next_action_correct"], 1)
            self.assertEqual(metrics["overall"]["context_policy_correct"], 1)
            self.assertEqual(metrics["overall"]["executor_kind_correct"], 2)
            self.assertIn("architecture|tier=small|next=next_subtask", metrics["by_stratum"])
            self.assertIn("legacy", metrics["by_source_mode"])
            self.assertEqual(metrics["by_source_mode"]["legacy"]["rows"], 2)
            self.assertEqual(metrics["parse_failures_sample"][0]["line_number"], 3)

    def test_reference_and_compact_normalization_score_generation_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            reference = root / "reference.jsonl"
            generations = root / "generations.jsonl"
            output_dir = root / "eval"
            _write_jsonl(
                reference,
                [
                    _sft_row(
                        transition_id="t1",
                        source_mode="architecture",
                        stratum="architecture|tier=medium|next=await_human",
                        labels={
                            "model_tier": "medium",
                            "next_action": "await_human",
                            "context_policy": "progressive_context",
                            "executor_kind": "workspace_tool",
                        },
                        target=_target(
                            model_tier="medium",
                            next_action="await_human",
                            context_policy="progressive_context",
                            executor_kind="workspace_tool",
                        ),
                    )
                ],
            )
            _write_jsonl(
                generations,
                [
                    {
                        "line_number": 1,
                        "model_label": "adapter",
                        "generated_text": (
                            "{\"model_tier\":\"medium\",\"context_policy\":\"progressive_context\","
                            "\"executor_kind\":\"workspace_tool\",\"verifier_next_action\":\"await_human\"}"
                        ),
                    }
                ],
            )

            subprocess.run(
                [
                    sys.executable,
                    str(EVAL_PATH),
                    "--input",
                    str(generations),
                    "--reference",
                    str(reference),
                    "--normalize-compact",
                    "--output-dir",
                    str(output_dir),
                ],
                check=True,
                text=True,
                capture_output=True,
            )

            metrics = json.loads((output_dir / "metrics.json").read_text(encoding="utf-8"))
            self.assertEqual(metrics["overall"]["rows"], 1)
            self.assertEqual(metrics["overall"]["schema_valid_count"], 1)
            self.assertEqual(metrics["overall"]["normalized_count"], 1)
            self.assertEqual(metrics["overall"]["model_tier_accuracy"], 1.0)
            self.assertEqual(metrics["overall"]["next_action_accuracy"], 1.0)
            self.assertEqual(metrics["overall"]["context_policy_accuracy"], 1.0)
            self.assertEqual(metrics["overall"]["executor_kind_accuracy"], 1.0)
            self.assertIn("architecture|tier=medium|next=await_human", metrics["by_stratum"])
            self.assertEqual(metrics["by_model_label"]["adapter"]["rows"], 1)

    def test_compact_normalization_canonicalizes_domain_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            reference = root / "reference.jsonl"
            generations = root / "generations.jsonl"
            output_dir = root / "eval"
            _write_jsonl(
                reference,
                [
                    _sft_row(
                        transition_id="t1",
                        source_mode="architecture",
                        stratum="architecture|tier=small|next=next_subtask",
                        labels={
                            "model_tier": "small",
                            "next_action": "next_subtask",
                            "context_policy": "permission_policy+risk_terms",
                            "executor_kind": "policy_gate",
                        },
                        target=_target(
                            model_tier="small",
                            next_action="next_subtask",
                            context_policy="permission_policy+risk_terms",
                            executor_kind="policy_gate",
                        ),
                    )
                ],
            )
            _write_jsonl(
                generations,
                [
                    {
                        "line_number": 1,
                        "model_label": "adapter",
                        "generated_text": (
                            "{\"model_tier\":\"small\","
                            "\"context_policy\":\"permission_policy+safety_terms\","
                            "\"executor_kind\":\"risk_model\","
                            "\"verifier_next_action\":\"await_human_or_next_goal\"}"
                        ),
                    }
                ],
            )

            subprocess.run(
                [
                    sys.executable,
                    str(EVAL_PATH),
                    "--input",
                    str(generations),
                    "--reference",
                    str(reference),
                    "--normalize-compact",
                    "--output-dir",
                    str(output_dir),
                ],
                check=True,
                text=True,
                capture_output=True,
            )

            metrics = json.loads((output_dir / "metrics.json").read_text(encoding="utf-8"))
            self.assertEqual(metrics["overall"]["schema_valid_rate"], 1.0)
            self.assertEqual(metrics["overall"]["next_action_accuracy"], 1.0)
            self.assertEqual(metrics["overall"]["context_policy_accuracy"], 1.0)
            self.assertEqual(metrics["overall"]["executor_kind_accuracy"], 1.0)


def _target(
    *,
    model_tier: str,
    next_action: str,
    context_policy: str,
    executor_kind: str,
) -> dict:
    return {
        "analysis": "Pick an architecture action.",
        "plan": "Use the selected tier and verifier action.",
        "commands": [
            {
                "keystrokes": (
                    "openclaw.plan_subtask "
                    f"--tool planner --model-tier {model_tier} "
                    f"--context-policy {context_policy} --next-action {next_action}"
                ),
                "duration": 1,
            }
        ],
        "task_complete": False,
        "architecture": {
            "task_id": "task",
            "tool_name": "planner",
            "action": "Build the next subtask.",
            "model_tier": model_tier,
            "risk_level": "low",
            "context_policy": context_policy,
            "memory_queries": ["tool:planner"],
            "success_criteria": ["evidence is recorded"],
            "executor_kind": executor_kind,
            "expected_next_action": next_action,
        },
        "verifier": {
            "outcome": "completed",
            "decision_behavior": "allow",
            "next_action": next_action,
            "evidence_complete": True,
            "residual_risk": 0,
        },
    }


def _sft_row(
    *,
    transition_id: str,
    source_mode: str,
    stratum: str,
    labels: dict,
    target: dict,
) -> dict:
    return {
        "source": "openclaw_architecture_events",
        "transition_id": transition_id,
        "source_mode": source_mode,
        "balance_stratum": stratum,
        "model_tier": labels["model_tier"],
        "next_action": labels["next_action"],
        "labels": {
            "context_policy": labels["context_policy"],
            "executor_kind": labels["executor_kind"],
        },
        "text": (
            "<|im_start|>system\nReturn JSON.\n<|im_end|>\n"
            "<|im_start|>user\nGoal: Optimize planner architecture.\n<|im_end|>\n"
            f"<|im_start|>assistant\n{json.dumps(target, ensure_ascii=False, separators=(',', ':'))}<|im_end|>\n"
        ),
    }


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    unittest.main()
