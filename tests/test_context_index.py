import tempfile
import unittest
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from openclaw.as2_adapter import AS2Status
from openclaw.context_index import ContextIndex
from openclaw.models import AuditEvent, RunState, new_run_id
from openclaw.permissions import PermissionEngine
from openclaw.planner import LocalAuditPlanner
from openclaw.storage import RunStorage


class ContextIndexTest(unittest.TestCase):
    def test_cross_run_recall_returns_source_backed_snippet(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            index = ContextIndex(Path(temp_dir) / "context.sqlite3")
            record_id = index.archive_record(
                run_id="run_alpha_context_seed",
                kind="final",
                title="ALPHA-CONTEXT-42 memory seed",
                body="ALPHA-CONTEXT-42 refers to the SQLite FTS archival memory prototype.",
                source="context_index",
                metadata={"evidence": "priority_1_midterm"},
            )

            hits = index.search(
                "What does ALPHA-CONTEXT-42 refer to?",
                top_k=5,
                exclude_run_id="run_alpha_context_query",
            )
            current_run_hits = index.search(
                "What does ALPHA-CONTEXT-42 refer to?",
                top_k=5,
                exclude_run_id="run_alpha_context_seed",
            )

            self.assertGreaterEqual(len(hits), 1)
            self.assertEqual(hits[0].record_id, record_id)
            self.assertEqual(hits[0].run_id, "run_alpha_context_seed")
            self.assertEqual(hits[0].kind, "final")
            self.assertEqual(hits[0].source, "context_index")
            self.assertTrue(hits[0].created_at)
            snippets = index.render_snippets(hits)
            self.assertIn("record_id", snippets[0])
            self.assertIn("run_id", snippets[0])
            self.assertIn("kind", snippets[0])
            self.assertIn("source", snippets[0])
            self.assertIn("created_at", snippets[0])
            self.assertIn("snippet", snippets[0])
            self.assertIn("SQLite FTS archival memory prototype", snippets[0]["snippet"])
            self.assertEqual(current_run_hits, [])
            payload = index.render_payload(hits)
            self.assertIn("retrieved_context", payload)
            self.assertEqual(payload["retrieved_context"][0]["record_id"], record_id)

    def test_archive_run_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            index = ContextIndex(Path(temp_dir) / "context.sqlite3")
            state = RunState(
                run_id="run_alpha_context",
                goal="Remember ALPHA-CONTEXT-42 as the SQLite FTS archival memory prototype.",
                permission_mode="DEFAULT",
                workspace_path=temp_dir,
                final_response="ALPHA-CONTEXT-42 means the SQLite FTS archival memory prototype.",
                status="completed",
            )
            events = [
                AuditEvent(
                    run_id=state.run_id,
                    event_id=1,
                    event_type="planning",
                    message="Selected planner path.",
                    data={
                        "selected_titles": ["Read archived context snippets"],
                        "selected_tools": ["audit_reader"],
                        "planner_strategy": "greedy_topk",
                        "selection_rule": "test",
                    },
                ),
            ]

            first_records = index.archive_run(state, events)
            second_records = index.archive_run(state, events)
            hits = index.search("What does ALPHA-CONTEXT-42 mean?", limit=10)

            self.assertEqual(len(first_records), len(second_records))
            self.assertGreaterEqual(len(hits), 1)
            self.assertEqual(len({record.record_key for record in hits}), len(hits))
            self.assertTrue(any(record.run_id == state.run_id for record in hits))

    def test_planner_retrieves_and_injects_context_from_prior_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage = RunStorage(Path(temp_dir))
            planner = LocalAuditPlanner(
                storage=storage,
                permission_engine=PermissionEngine(),
                as2_status=AS2Status(
                    available=False,
                    package_version=None,
                    runtime="test",
                    note="test",
                ),
            )

            first = RunState(
                run_id=new_run_id(),
                goal="Remember ALPHA-CONTEXT-42 as the SQLite FTS archival memory prototype.",
                permission_mode="DEFAULT",
                workspace_path=temp_dir,
            )
            storage.create_run(first)
            planner.run(first)

            second = RunState(
                run_id=new_run_id(),
                goal="Use previous project memory to explain ALPHA-CONTEXT-42.",
                permission_mode="DEFAULT",
                workspace_path=temp_dir,
            )
            storage.create_run(second)
            planner.run(second)

            events = storage.load_events(second.run_id)
            retrieval_event = next(event for event in events if event.event_type == "context_retrieval")
            injection_event = next(event for event in events if event.event_type == "context_injection")

            self.assertGreaterEqual(retrieval_event.data["hit_count"], 1)
            self.assertIn(first.run_id, retrieval_event.data["source_run_ids"])
            self.assertGreaterEqual(injection_event.data["snippet_count"], 1)

            candidate_events = [event for event in events if event.event_type == "candidate_step"]
            candidate_tools = {
                event.data["candidate"]["tool_name"]
                for event in candidate_events
            }
            self.assertIn("audit_reader", candidate_tools)


if __name__ == "__main__":
    unittest.main()
