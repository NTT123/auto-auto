"""
Test the loop/iteration system.

Tests: starting loops, iteration tracking, convergence detection,
update/close iterations, and the full loop lifecycle.
"""

import asyncio
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


WORKFLOW_WITH_LOOP = {
    "name": "test-loop-workflow",
    "goal": "Test the loop system",
    "pattern": "iterative-refinement",
    "initial_state": "plan",
    "states": {
        "plan": {
            "instruction": "Plan the work.",
            "transitions": {"execute": {"requires": ["all_tasks_defined"]}},
        },
        "execute": {
            "instruction": "Do the work.",
            "transitions": {"verify": {"requires": ["all_tasks_done"]}},
        },
        "verify": {
            "instruction": "Verify the work.",
            "transitions": {
                "done": {"requires": ["gate_passed"]},
                "improve": {},
            },
        },
        "improve": {
            "instruction": "Improve based on feedback.",
            "transitions": {
                "verify": {},
                "done": {},
            },
        },
        "done": {
            "instruction": "Complete.",
            "transitions": {},
        },
    },
    "verification": {
        "strategy": "automated_tests",
        "checks": [
            {"criteria": "Tests pass", "method": "automated_tests", "how": "Run pytest"},
        ],
    },
}


async def test_loop():
    tmpdir = Path(tempfile.mkdtemp())
    workflow_dir = tmpdir / ".workflow"
    workflow_dir.mkdir()

    os.environ["WORKFLOW_DIR"] = str(workflow_dir)

    import importlib
    import workflow_engine.server as srv
    importlib.reload(srv)
    mcp = srv.mcp

    try:
        # Init workflow
        await mcp.call_tool("wf_init", {"config_json": json.dumps(WORKFLOW_WITH_LOOP)})

        # Get through to verify state quickly
        await mcp.call_tool("wf_task", {"action": "create", "name": "Build v1"})
        await mcp.call_tool("wf_transition", {"to_state": "execute"})
        await mcp.call_tool("wf_task", {"action": "done", "task_id": "t1"})
        await mcp.call_tool("wf_transition", {"to_state": "verify"})
        await mcp.call_tool("wf_gate", {
            "criteria": "Tests pass", "passed": True, "evidence": "All green",
        })
        print("✓ 0. Setup: reached verify state with v1")

        # ── 1. Start loop ──
        result = await mcp.call_tool("wf_loop", {
            "action": "start",
            "focus": "Improve error handling and edge cases",
        })
        data = result.structured_content
        assert data["started"] is True
        assert data["iteration"] == 1
        assert data["focus"] == "Improve error handling and edge cases"
        print("✓ 1. Loop started (iteration 1)")

        # ── 2. Loop status ──
        result = await mcp.call_tool("wf_loop", {"action": "status"})
        data = result.structured_content
        assert data["active"] is True
        assert data["current_iteration"] == 1
        assert data["total_iterations"] == 1
        print("✓ 2. Loop status shows active, iteration 1")

        # ── 3. Update iteration with results ──
        result = await mcp.call_tool("wf_loop", {
            "action": "update",
            "outcome": "Added try/catch blocks and input validation",
            "improvements": ["Error messages now descriptive", "Input validated on all endpoints"],
            "remaining_issues": ["No retry logic", "Missing timeout handling", "Logging incomplete"],
        })
        data = result.structured_content
        assert data["updated"] is True
        assert data["remaining_issues"] == ["No retry logic", "Missing timeout handling", "Logging incomplete"]
        print("✓ 3. Iteration 1 updated with results (3 remaining issues)")

        # ── 4. Close iteration 1, continue looping ──
        result = await mcp.call_tool("wf_loop", {
            "action": "update",
            "verdict": "continue",
        })
        data = result.structured_content
        assert "next iteration" in data["hint"].lower() or "wf_loop" in data["hint"]
        print("✓ 4. Iteration 1 closed with verdict='continue'")

        # ── 5. Start iteration 2 ──
        # Transition to improve state, then back to verify
        await mcp.call_tool("wf_transition", {"to_state": "improve"})

        result = await mcp.call_tool("wf_loop", {
            "action": "next",
            "focus": "Add retry logic and timeout handling",
        })
        data = result.structured_content
        assert data["iteration"] == 2
        print("✓ 5. Iteration 2 started")

        # Do work, transition back to verify
        await mcp.call_tool("wf_transition", {"to_state": "verify"})

        # ── 6. Update iteration 2 ──
        result = await mcp.call_tool("wf_loop", {
            "action": "update",
            "outcome": "Added retry with exponential backoff, 30s timeouts",
            "improvements": ["Retry logic on all HTTP calls", "Timeouts configured"],
            "remaining_issues": ["Logging still incomplete"],
            "verdict": "continue",
        })
        data = result.structured_content
        assert data["updated"] is True
        print("✓ 6. Iteration 2 updated (1 remaining issue — converging!)")

        # ── 7. Check convergence ──
        result = await mcp.call_tool("wf_loop", {"action": "status"})
        data = result.structured_content
        assert data["converging"] is True  # 3 issues → 1 issue
        assert data["issue_trend"] == [3, 1]
        assert data["current_iteration"] == 2
        print("✓ 7. Convergence detected: issues trending down [3, 1]")

        # ── 8. Iteration 3 — final fix ──
        await mcp.call_tool("wf_transition", {"to_state": "improve"})
        result = await mcp.call_tool("wf_loop", {
            "action": "next",
            "focus": "Complete logging",
        })
        assert result.structured_content["iteration"] == 3

        await mcp.call_tool("wf_transition", {"to_state": "verify"})

        result = await mcp.call_tool("wf_loop", {
            "action": "update",
            "outcome": "Added structured logging with correlation IDs",
            "improvements": ["Full request/response logging", "Error correlation"],
            "remaining_issues": [],
            "verdict": "done",
        })
        data = result.structured_content
        assert data["loop_complete"] is True
        assert data["total_iterations"] == 3
        print("✓ 8. Iteration 3 done — loop complete after 3 iterations")

        # ── 9. Loop status after completion ──
        result = await mcp.call_tool("wf_loop", {"action": "status"})
        data = result.structured_content
        assert data["active"] is False
        assert data["total_iterations"] == 3
        assert data["issue_trend"] == [3, 1, 0]
        assert data["converging"] is True
        print("✓ 9. Final status: 3 iterations, converging, 0 remaining issues")

        # ── 10. wf_status includes loop info ──
        result = await mcp.call_tool("wf_status", {})
        data = result.structured_content
        assert data["loop"] is not None
        assert data["loop"]["total_iterations"] == 3
        print("✓ 10. wf_status includes loop summary")

        # ── 11. Persistence ──
        import workflow_engine.server as srv2
        importlib.reload(srv2)
        result = await srv2.mcp.call_tool("wf_loop", {"action": "status"})
        data = result.structured_content
        assert data["total_iterations"] == 3
        assert data["active"] is False
        print("✓ 11. Loop state persisted and reloaded correctly")

        # ── 12. Can't start next without closing current ──
        await mcp.call_tool("wf_init", {"config_json": json.dumps(WORKFLOW_WITH_LOOP)})
        await mcp.call_tool("wf_loop", {"action": "start", "focus": "Test block"})
        result = await mcp.call_tool("wf_loop", {"action": "next", "focus": "Should fail"})
        data = result.structured_content
        assert "error" in data
        assert "not closed" in data["error"].lower() or "verdict" in data["error"].lower()
        print("✓ 12. Can't start next iteration without closing current")

        print("\n🎉 All loop tests passed!")

    finally:
        shutil.rmtree(tmpdir)
        os.environ.pop("WORKFLOW_DIR", None)


if __name__ == "__main__":
    asyncio.run(test_loop())
