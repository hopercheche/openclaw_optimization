import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROMOTION_PATH = (
    PROJECT_ROOT
    / "data"
    / "litangchao"
    / "OpentClawOpti"
    / "Agent_Planner"
    / "scripts"
    / "check_architecture_policy_promotion.py"
)


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class OpenClawArchitecturePolicyPromotionTest(unittest.TestCase):
    def test_promotes_shadow_but_blocks_learned_replacement_when_ablation_depends_on_rules(self) -> None:
        promotion = load_module(PROMOTION_PATH, "check_architecture_policy_promotion")
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target = _write_metrics(root / "target", _target_metrics(rows=1000))
            classifier = _write_metrics(root / "classifier", _classifier_metrics(rows=1000))
            hard_negative = _write_metrics(root / "hard_negative", _classifier_metrics(rows=5216))
            runtime_shadow = _write_metrics(root / "runtime_shadow", _classifier_metrics(rows=860))
            ablation = _write_metrics(
                root / "ablation",
                _ablation_metrics(full=1.0, no_tool=0.0, no_next=0.6, no_permission=0.78, no_hazard=0.65),
            )
            adapter_summary = _write_json(root / "adapter_summary.json", _adapter_summary())

            report = promotion.check_promotion(
                target_eval=target,
                classifier_eval=classifier,
                hard_negative_eval=hard_negative,
                ablation_eval=ablation,
                adapter_summary=adapter_summary,
                runtime_shadow_eval=runtime_shadow,
                output_dir=root / "promotion",
            )

            self.assertEqual(report["gates"]["adapter_train_ready"]["status"], "pass")
            self.assertEqual(report["gates"]["runtime_shadow_ready"]["status"], "pass")
            self.assertEqual(report["gates"]["learned_replacement_ready"]["status"], "fail")
            self.assertEqual(report["recommendation"]["level"], "promote_runtime_shadow_only")
            self.assertIn("ablation_rule_dependency", report["gates"]["learned_replacement_ready"]["failed_sections"])
            self.assertTrue((root / "promotion" / "promotion_report.json").exists())
            self.assertTrue((root / "promotion" / "promotion_report.md").exists())

    def test_blocks_runtime_when_hard_negative_sample_is_too_small(self) -> None:
        promotion = load_module(PROMOTION_PATH, "check_architecture_policy_promotion")
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target = _write_metrics(root / "target", _target_metrics(rows=1000))
            classifier = _write_metrics(root / "classifier", _classifier_metrics(rows=1000))
            hard_negative = _write_metrics(root / "hard_negative", _classifier_metrics(rows=64))
            runtime_shadow = _write_metrics(root / "runtime_shadow", _classifier_metrics(rows=860))
            ablation = _write_metrics(root / "ablation", _ablation_metrics())
            adapter_summary = _write_json(root / "adapter_summary.json", _adapter_summary())

            report = promotion.check_promotion(
                target_eval=target,
                classifier_eval=classifier,
                hard_negative_eval=hard_negative,
                ablation_eval=ablation,
                adapter_summary=adapter_summary,
                runtime_shadow_eval=runtime_shadow,
                output_dir=root / "promotion",
            )

            self.assertEqual(report["gates"]["adapter_train_ready"]["status"], "pass")
            self.assertEqual(report["gates"]["runtime_shadow_ready"]["status"], "fail")
            self.assertEqual(report["recommendation"]["level"], "train_adapter_next")
            self.assertIn("hard_negative_eval", report["gates"]["runtime_shadow_ready"]["failed_sections"])
            self.assertIn("rows", report["checks"]["hard_negative_eval"]["failed_requirements"])


def _write_metrics(path: Path, payload: dict) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return _write_json(path / "metrics.json", payload)


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _target_metrics(*, rows: int) -> dict:
    return {
        "overall": {
            "rows": rows,
            "schema_valid_rate": 1.0,
            "architecture_valid_rate": 1.0,
            "verifier_valid_rate": 1.0,
            "model_tier_accuracy": 1.0,
            "next_action_accuracy": 1.0,
            "context_policy_accuracy": 1.0,
            "executor_kind_accuracy": 1.0,
        }
    }


def _classifier_metrics(*, rows: int) -> dict:
    return {
        "overall": {
            "rows": rows,
            "exact_match_rate": 1.0,
            "mean_prediction_seconds": 0.00008,
            "model_tier_accuracy": 1.0,
            "verifier_next_action_accuracy": 1.0,
            "context_policy_accuracy": 1.0,
            "executor_kind_accuracy": 1.0,
            "strategist_exact_rate": 1.0,
            "architect_exact_rate": 1.0,
        }
    }


def _ablation_metrics(
    *,
    full: float = 1.0,
    no_tool: float = 1.0,
    no_next: float = 1.0,
    no_permission: float = 1.0,
    no_hazard: float = 1.0,
) -> dict:
    def section(rate: float) -> dict:
        return {"rows": 1000, "exact_match_rate": rate}

    return {
        "rows": 1000,
        "ablations": {
            "full": section(full),
            "no_tool_priors": section(no_tool),
            "no_next_action_prior": section(no_next),
            "no_permission_guards": section(no_permission),
            "no_hazard_guards": section(no_hazard),
        },
    }


def _adapter_summary() -> dict:
    return {
        "rows_written": 1000,
        "source_mix_counts": {"rule_distillation": 110, "perturbation": 890},
        "perturbation_type_counts": {
            "dangerous_action_guard": 100,
            "expected_next_action_distractor": 100,
            "implicit_semantic_tool_failure": 100,
            "permission_mode_rewrite": 100,
            "rule_distillation": 100,
            "tool_action_distractor": 100,
            "tool_name_confusion": 100,
            "tool_unreliability_replan": 100,
            "unsolvable_task_refusal": 100,
        },
        "expected_next_action_counts": {
            "await_human": 320,
            "next_subtask": 350,
            "replan": 330,
        },
    }


if __name__ == "__main__":
    unittest.main()
