import os
import unittest
from pathlib import Path
from unittest.mock import patch

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from openclaw.as2_adapter import (
    build_user_message_snapshot,
    detect_as2,
    map_local_event_to_as2,
    resolve_model_provider_config,
)
from openclaw.as2_openai import _parse_candidates, _sanitize_error


class AS2AdapterTest(unittest.TestCase):
    def test_detects_installed_agentscope(self) -> None:
        status = detect_as2()

        self.assertTrue(status.available)
        self.assertTrue(status.package_version.startswith("2.0."))
        self.assertTrue(status.primitives["Agent"])
        self.assertIn("REPLY_START", status.event_types)

    def test_builds_real_user_message_snapshot(self) -> None:
        snapshot = build_user_message_snapshot("hello audit", "run_test")

        self.assertTrue(snapshot["available"])
        self.assertEqual(snapshot["role"], "user")
        self.assertEqual(snapshot["text"], "hello audit")
        self.assertEqual(snapshot["metadata"]["run_id"], "run_test")

    def test_deepseek_provider_config(self) -> None:
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "secret"}, clear=True):
            config = resolve_model_provider_config()

        self.assertEqual(config.provider, "deepseek")
        self.assertEqual(config.base_url, "https://api.deepseek.com")
        self.assertEqual(config.model, "deepseek-v4-flash")

    def test_maps_permission_ask_to_as2_human_gate(self) -> None:
        mapped = map_local_event_to_as2("permission", {
            "decision": {
                "behavior": "ask",
            },
        })

        self.assertEqual(mapped, "REQUIRE_USER_CONFIRM")

    def test_parses_as2_candidate_json(self) -> None:
        candidates = _parse_candidates(
            """
            {
              "candidates": [
                {
                  "title": "Inspect",
                  "action": "List files safely",
                  "tool_name": "workspace_inspector",
                  "rationale": "Collect evidence",
                  "impact": 4,
                  "evidence_value": 5,
                  "reversibility": 5,
                  "risk": 1,
                  "mutates_workspace": false
                }
              ],
              "strategy_notes": ["bounded"]
            }
            """
        )

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].tool_name, "workspace_inspector")
        self.assertEqual(candidates[0].score, 17)

    def test_sanitizes_api_key_fragments(self) -> None:
        message = (
            "Incorrect API key provided: "
            + "sk-"
            + "test****************abcd. You can find your API key at "
            "https://platform."
            "openai.com/account/api-keys."
        )

        sanitized = _sanitize_error(message)

        self.assertNotIn("sk-test", sanitized)
        self.assertNotIn("platform." + "openai.com", sanitized)
        self.assertIn("[redacted]", sanitized)


if __name__ == "__main__":
    unittest.main()
