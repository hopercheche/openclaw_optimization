import asyncio
import tempfile
import unittest
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from openclaw.as2_runtime import (
    OPENCLAW_TOOL_NAMES,
    build_as2_agent_state,
    build_openclaw_as2_toolkit,
    describe_as2_architecture,
)


def _registered_tools(toolkit):
    tools = []
    for group in toolkit.tool_groups:
        for item in group.tools:
            tools.append(getattr(item, "tool", item))
    return tools


class AS2RuntimeTest(unittest.TestCase):
    def test_describes_full_agent_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            architecture = describe_as2_architecture(temp_dir, "DEFAULT")

        self.assertTrue(architecture["agent_runtime_ready"])
        self.assertTrue(architecture["toolkit_ready"])
        self.assertTrue(OPENCLAW_TOOL_NAMES.issubset(set(architecture["tool_names"])))
        self.assertIn("app_server_ready", architecture)

    def test_builds_as2_agent_state_with_workspace_scope(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state = build_as2_agent_state("run_test", "EXPLORE", temp_dir)
            workspace = str(Path(temp_dir).resolve())

        self.assertEqual(state.session_id, "run_test")
        self.assertEqual(state.permission_context.mode.value, "explore")
        self.assertIn(workspace, state.permission_context.working_directories)

    def test_openclaw_toolkit_registers_read_only_tools(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            toolkit = build_openclaw_as2_toolkit(temp_dir, "DEFAULT")
            tools = _registered_tools(toolkit)

        names = {tool.name for tool in tools}
        self.assertTrue(OPENCLAW_TOOL_NAMES.issubset(names))

        schema_tool = next(tool for tool in tools if tool.name == "openclaw_audit_schema")
        state = build_as2_agent_state("run_test", "DEFAULT", tempfile.gettempdir())
        decision = asyncio.run(schema_tool.check_permissions({}, state.permission_context))
        self.assertEqual(decision.behavior.value, "allow")


if __name__ == "__main__":
    unittest.main()
