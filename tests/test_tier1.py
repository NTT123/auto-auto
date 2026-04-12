"""
Tier 1 feature tests: brief-mode wf_status, wf_resume, next_action hints,
and gate iteration tagging.

These tests exist because of user feedback that auto-auto was "over-reporting
and under-guiding": wf_status was a firehose, there was no compaction-recovery
view, no 'what to do next' hint on responses, and gate evidence had to be
manually tagged with 'Iter4 re-run' strings to spot regressions.
"""

import asyncio
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


WORKFLOW = {
    "name": "tier1-test",
    "goal": "Test Tier 1 improvements",
    "pattern": "iterative-refinement",
    "initial_state": "plan",
    "states": {
        "plan": {
            "instruction": (
                "Plan the work. This instruction is intentionally long and "
                "verbose so we can verify that brief mode does NOT return it "
                "but full mode does. Break the goal down into specific tasks, "
                "think about edge cases, identify unknowns. Take notes. Only "
                "when the plan is solid should you transition to execute."
            ),
            "transitions": {"execute": {"requires": ["all_tasks_defined"]}},
        },
        "execute": {
            "instruction": "Do the work.",
            "transitions": {"verify": {"requires": ["all_tasks_done"]}},
        },
        "verify": {
            "instruction": "Verify the work using the verification plan.",
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
    "verification": {
        "strategy": "automated_tests",
        "description": "Run the pytest suite.",
        "checks": [
            {
                "criteria": "Unit tests pass",
                "method": "automated_tests",
                "how": "Run pytest and check for 0 failures",
                "command": "python -m pytest tests/ -v",
            },
            {
                "criteria": "Integration tests pass",
                "method": "automated_tests",
                "how": "Run integration tests",
                "command": "python -m pytest tests/integration/ -v",
            },
        ],
    },
}


async def test_tier1():
    tmpdir = Path(tempfile.mkdtemp())
    workflow_dir = tmpdir / ".workflow"
    workflow_dir.mkdir()

    os.environ["WORKFLOW_DIR"] = str(workflow_dir)

    import importlib
    import workflow_engine.server as srv
    importlib.reload(srv)
    mcp = srv.mcp

    try:
        # Init the workflow
        await mcp.call_tool("wf_init", {"config_json": json.dumps(WORKFLOW)})

        # ── 1. wf_status defaults to brief mode ──
        result = await mcp.call_tool("wf_status", {})
        data = result.structured_content
        assert data["mode"] == "brief", (
            f"wf_status() should default to brief mode, got {data.get('mode')!r}"
        )
        # Brief mode must include the small signals …
        assert data["loaded"] is True
        assert data["current_state"] == "plan"
        assert data["workflow"]["goal"] == "Test Tier 1 improvements"
        assert "task_summary" in data
        assert "verification" in data
        assert "transitions" in data
        # … and must EXCLUDE the firehose fields
        assert "instruction" not in data, (
            "Brief mode must not include the full instruction text"
        )
        assert "tasks_in_state" not in data, (
            "Brief mode must not include tasks_in_state"
        )
        assert "recent_reflections" not in data, (
            "Brief mode must not include recent_reflections"
        )
        print("✓ 1. wf_status() defaults to brief mode and trims firehose fields")

        # ── 2. wf_status(mode='full') restores the full dashboard ──
        result = await mcp.call_tool("wf_status", {"mode": "full"})
        data = result.structured_content
        assert data["mode"] == "full"
        assert data["instruction"], "Full mode must include instruction text"
        assert data["instruction"].startswith("Plan the work.")
        assert "tasks_in_state" in data
        assert "recent_reflections" in data
        print("✓ 2. wf_status(mode='full') restores instruction and firehose fields")

        # ── 3. Invalid mode rejected ──
        result = await mcp.call_tool("wf_status", {"mode": "bogus"})
        data = result.structured_content
        assert "error" in data
        assert "brief" in data["error"] and "full" in data["error"]
        print("✓ 3. wf_status(mode='bogus') is rejected with a clear error")

        # ── 4. next_action hint on wf_status brief (plan state, no tasks) ──
        result = await mcp.call_tool("wf_status", {})
        data = result.structured_content
        assert "next_action" in data, "wf_status must include next_action hint"
        na = data["next_action"]
        assert na["kind"] == "define_tasks", (
            f"In plan state with no tasks, next_action should be 'define_tasks', "
            f"got {na['kind']}"
        )
        assert "wf_task" in na["suggestion"]
        print(f"✓ 4. next_action hint suggests defining tasks in plan state: {na['kind']}")

        # ── 5. next_action updates after creating a task ──
        await mcp.call_tool("wf_task", {
            "action": "create", "name": "Build the thing",
        })
        result = await mcp.call_tool("wf_status", {})
        data = result.structured_content
        na = data["next_action"]
        # Tasks are now defined, so next_action should be 'transition' to execute
        assert na["kind"] == "transition"
        assert na.get("target") == "execute"
        print(f"✓ 5. next_action flips to 'transition' once tasks are defined")

        # ── 6. In execute state with pending tasks, next_action says start_task ──
        await mcp.call_tool("wf_transition", {"to_state": "execute"})
        result = await mcp.call_tool("wf_state", {})
        data = result.structured_content
        assert "next_action" in data
        na = data["next_action"]
        assert na["kind"] == "start_task"
        assert na.get("task_id") == "t1"
        print(f"✓ 6. next_action in execute with pending task suggests 'start_task'")

        # ── 7. In verify state with pending checks, next_action says run_check ──
        await mcp.call_tool("wf_task", {"action": "done", "task_id": "t1"})
        await mcp.call_tool("wf_transition", {"to_state": "verify"})
        result = await mcp.call_tool("wf_state", {})
        data = result.structured_content
        na = data["next_action"]
        assert na["kind"] == "run_check"
        assert na["criteria"] == "Unit tests pass"
        assert na["command"] == "python -m pytest tests/ -v"
        print(f"✓ 7. next_action in verify with pending check suggests 'run_check'")

        # ── 8. wf_gate defaults iteration to 0 when no loop is active ──
        result = await mcp.call_tool("wf_gate", {
            "criteria": "Unit tests pass",
            "passed": True,
            "evidence": "pytest: 5 passed, 0 failed",
        })
        data = result.structured_content
        assert data["passed"] is True
        assert data["iteration"] == 0, (
            f"Gate with no loop should default to iteration 0, got {data.get('iteration')}"
        )
        # next_action should point at the next pending check
        assert data["next_action"]["kind"] == "run_check"
        assert data["next_action"]["criteria"] == "Integration tests pass"
        print("✓ 8. wf_gate defaults iteration=0 pre-loop and chains next_action")

        # ── 9. Pass second check, check next_action flips to transition ──
        await mcp.call_tool("wf_gate", {
            "criteria": "Integration tests pass",
            "passed": True,
            "evidence": "pytest: 8 passed, 0 failed",
        })
        result = await mcp.call_tool("wf_status", {})
        data = result.structured_content
        assert data["verification"]["pending_checks"] == 0
        assert data["next_action"]["kind"] == "transition"
        assert data["next_action"]["target"] == "done"
        print("✓ 9. next_action flips to 'transition' once all checks pass")

        # ── 10. wf_resume() returns a narrative + next_action ──
        result = await mcp.call_tool("wf_resume", {})
        data = result.structured_content
        assert data["loaded"] is True
        assert "narrative" in data
        assert "verify" in data["narrative"]
        assert "2/2" in data["narrative"], (
            f"Narrative should mention 2/2 gates passing, got: {data['narrative']}"
        )
        assert data["next_action"]["kind"] == "transition"
        assert data["current_state"] == "verify"
        print("✓ 10. wf_resume() returns narrative + structured fields + next_action")

        # ── 11. Gate iteration tagging with an active loop ──
        # Transition to done to reset, then start a new workflow to test loop iteration
        await mcp.call_tool("wf_transition", {"to_state": "done"})

        # Re-init for a loop test
        await mcp.call_tool("wf_init", {"config_json": json.dumps(WORKFLOW)})
        await mcp.call_tool("wf_task", {"action": "create", "name": "v1"})
        await mcp.call_tool("wf_transition", {"to_state": "execute"})
        await mcp.call_tool("wf_task", {"action": "done", "task_id": "t1"})
        await mcp.call_tool("wf_transition", {"to_state": "verify"})

        # Pre-loop gate (iteration 0)
        await mcp.call_tool("wf_gate", {
            "criteria": "Unit tests pass",
            "passed": True,
            "evidence": "v1 tests green",
        })

        # Start a loop
        await mcp.call_tool("wf_loop", {
            "action": "start", "focus": "Improve edge cases",
        })

        # Gate during iter 1 — should auto-infer iteration=1
        result = await mcp.call_tool("wf_gate", {
            "criteria": "Unit tests pass",
            "passed": True,
            "evidence": "iter1 tests green",
        })
        data = result.structured_content
        assert data["iteration"] == 1, (
            f"Gate in active loop iter 1 should auto-tag iteration=1, "
            f"got {data.get('iteration')}"
        )
        # criteria_history should now have 2 entries for this criteria
        assert "criteria_history" in data
        assert len(data["criteria_history"]) == 2
        assert data["criteria_history"][0]["iteration"] == 0
        assert data["criteria_history"][1]["iteration"] == 1
        assert "v1 tests green" in data["criteria_history"][0]["evidence_preview"]
        assert "iter1 tests green" in data["criteria_history"][1]["evidence_preview"]
        print("✓ 11. wf_gate auto-tags iteration during loop and returns criteria_history")

        # ── 12. wf_gate explicit iteration override ──
        result = await mcp.call_tool("wf_gate", {
            "criteria": "Unit tests pass",
            "passed": False,
            "evidence": "back-dated regression check",
            "iteration": 42,
        })
        data = result.structured_content
        assert data["iteration"] == 42
        print("✓ 12. wf_gate iteration param overrides the loop-inferred value")

        print("\n🎉 All Tier 1 tests passed!")

    finally:
        shutil.rmtree(tmpdir)
        os.environ.pop("WORKFLOW_DIR", None)


if __name__ == "__main__":
    asyncio.run(test_tier1())
