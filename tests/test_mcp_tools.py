"""Test MCP tools via the FastMCP async API."""

import asyncio
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


async def test_mcp_tools():
    tmpdir = Path(tempfile.mkdtemp())
    workflow_dir = tmpdir / ".workflow"

    # Set env before importing server
    os.environ["WORKFLOW_DIR"] = str(workflow_dir)

    # Re-import to pick up new WORKFLOW_DIR
    import importlib
    import workflow_engine.server as srv
    importlib.reload(srv)

    mcp = srv.mcp
    engine = srv.engine

    try:
        # ── 1. wf_status with no workflow ──
        result = await mcp.call_tool("wf_status", {})
        data = result.structured_content
        assert "error" in data or data.get("loaded") is False
        print("✓ 1. wf_status returns error when no workflow loaded")

        # ── 2. wf_init ──
        config = {
            "name": "mcp-test",
            "goal": "Test MCP tools",
            "pattern": "iterative",
            "initial_state": "plan",
            "states": {
                "plan": {
                    "instruction": "Plan your work.",
                    "transitions": {
                        "execute": {"requires": ["all_tasks_defined"]},
                    },
                },
                "execute": {
                    "instruction": "Do the work.",
                    "transitions": {
                        "verify": {"requires": ["all_tasks_done"]},
                    },
                },
                "verify": {
                    "instruction": "Check results.",
                    "transitions": {
                        "done": {"requires": ["gate_passed"]},
                        "execute": {},
                    },
                },
                "done": {
                    "instruction": "Complete.",
                    "transitions": {},
                },
            },
        }
        result = await mcp.call_tool("wf_init", {"config_json": json.dumps(config)})
        data = result.structured_content
        assert data["success"] is True
        assert data["initial_state"] == "plan"
        print("✓ 2. wf_init creates workflow")

        # ── 3. wf_status after init ──
        result = await mcp.call_tool("wf_status", {})
        data = result.structured_content
        assert data["loaded"] is True
        assert data["current_state"] == "plan"
        print("✓ 3. wf_status shows loaded workflow")

        # ── 4. wf_task create ──
        result = await mcp.call_tool("wf_task", {
            "action": "create",
            "name": "Write the code",
            "description": "Implement feature X",
        })
        data = result.structured_content
        assert "created" in data
        assert data["created"]["name"] == "Write the code"
        task_id = data["created"]["id"]
        print(f"✓ 4. wf_task create works (id={task_id})")

        # ── 5. wf_transition plan → execute ──
        result = await mcp.call_tool("wf_transition", {
            "to_state": "execute",
            "reason": "Plan is ready",
        })
        data = result.structured_content
        assert data["success"] is True
        print("✓ 5. wf_transition plan → execute")

        # ── 6. wf_transition blocked ──
        result = await mcp.call_tool("wf_transition", {"to_state": "verify"})
        data = result.structured_content
        assert data["success"] is False
        print("✓ 6. wf_transition blocked (tasks not done)")

        # ── 7. wf_task done ──
        result = await mcp.call_tool("wf_task", {
            "action": "done",
            "task_id": task_id,
        })
        data = result.structured_content
        assert data["updated"]["status"] == "done"
        print("✓ 7. wf_task done marks task complete")

        # ── 8. wf_transition to verify ──
        result = await mcp.call_tool("wf_transition", {
            "to_state": "verify",
            "reason": "Code done",
        })
        data = result.structured_content
        assert data["success"] is True
        print("✓ 8. wf_transition execute → verify")

        # ── 9. wf_gate ──
        result = await mcp.call_tool("wf_gate", {
            "criteria": "Tests pass",
            "passed": True,
            "evidence": "All 10 tests green",
        })
        data = result.structured_content
        assert data["passed"] is True
        print("✓ 9. wf_gate records pass")

        # ── 10. wf_reflect ──
        result = await mcp.call_tool("wf_reflect", {
            "content": "The iterative approach worked well for this test.",
        })
        data = result.structured_content
        assert "logged" in data
        print("✓ 10. wf_reflect logs reflection")

        # ── 11. wf_transition to done ──
        result = await mcp.call_tool("wf_transition", {
            "to_state": "done",
            "reason": "All verified",
        })
        data = result.structured_content
        assert data["success"] is True
        assert data["to"] == "done"
        print("✓ 11. wf_transition verify → done")

        # ── 12. wf_next at terminal state ──
        result = await mcp.call_tool("wf_next", {})
        data = result.structured_content
        assert data["transitions"] == {}
        print("✓ 12. wf_next shows no transitions at done")

        print("\n🎉 All MCP tool tests passed!")

    finally:
        shutil.rmtree(tmpdir)
        os.environ.pop("WORKFLOW_DIR", None)


if __name__ == "__main__":
    asyncio.run(test_mcp_tools())
