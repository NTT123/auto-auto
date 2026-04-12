"""
End-to-end test of the workflow engine.

Tests: init workflow, state transitions, task management, gates, reflections,
blocked transitions, and persistence.
"""

import asyncio
import json
import shutil
import sys
import tempfile
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from workflow_engine.engine import WorkflowEngine

# ── Test Workflow Config ─────────────────────────────────────────

TEST_WORKFLOW = {
    "name": "test-iterative",
    "goal": "Test the engine end to end",
    "pattern": "iterative-refinement",
    "initial_state": "plan",
    "states": {
        "plan": {
            "instruction": "Create a detailed plan with tasks.",
            "transitions": {
                "execute": {"requires": ["all_tasks_defined"]},
                "reflect": {},
            },
        },
        "execute": {
            "instruction": "Implement the plan step by step.",
            "transitions": {
                "verify": {"requires": ["all_tasks_done"]},
                "reflect": {},
            },
        },
        "verify": {
            "instruction": "Test and validate all changes.",
            "transitions": {
                "reflect": {},
                "done": {"requires": ["gate_passed"]},
                "plan": {},
            },
        },
        "reflect": {
            "instruction": "What worked? What didn't?",
            "transitions": {
                "plan": {},
                "execute": {},
                "done": {},
            },
        },
        "done": {
            "instruction": "Workflow complete.",
            "transitions": {},
        },
    },
}


def test_engine():
    """Run through the full workflow lifecycle."""
    tmpdir = Path(tempfile.mkdtemp())
    workflow_dir = tmpdir / ".workflow"
    workflow_dir.mkdir()

    try:
        # Write config
        config_path = workflow_dir / "config.json"
        config_path.write_text(json.dumps(TEST_WORKFLOW))

        # ── 1. Load ──
        engine = WorkflowEngine(workflow_dir)
        assert engine.is_loaded, "Engine should be loaded"
        assert engine.current_state == "plan", f"Should start in 'plan', got '{engine.current_state}'"
        print("✓ 1. Engine loads and starts in 'plan' state")

        # ── 2. Status ──
        status = engine.get_full_status()
        assert status["loaded"] is True
        assert status["workflow"]["name"] == "test-iterative"
        assert status["current_state"] == "plan"
        print("✓ 2. Full status works")

        # ── 3. Blocked transition (no tasks) ──
        result = engine.transition("execute")
        assert result["success"] is False, "Should be blocked — no tasks defined"
        assert "No tasks defined" in str(result["reasons"])
        print("✓ 3. Transition blocked: no tasks defined")

        # ── 4. Create tasks ──
        t1 = engine.create_task("Design API", "REST endpoints for auth")
        t2 = engine.create_task("Write tests", "Unit tests for API")
        assert t1.id == "t1"
        assert t2.id == "t2"
        tasks = engine.list_tasks(state="plan")
        assert len(tasks) == 2
        print("✓ 4. Tasks created and listed")

        # ── 5. Transition plan → execute (tasks defined) ──
        result = engine.transition("execute", reason="Plan is ready")
        assert result["success"] is True
        assert result["to"] == "execute"
        assert engine.current_state == "execute"
        print("✓ 5. Transition plan → execute succeeds")

        # ── 6. Blocked transition (tasks not done) ──
        result = engine.transition("verify")
        assert result["success"] is False
        print("✓ 6. Transition blocked: tasks not done")

        # ── 7. Complete tasks ──
        engine.update_task("t1", status="done")
        engine.update_task("t2", status="done")
        t1_updated = engine.tasks["t1"]
        assert t1_updated.completed_at is not None
        print("✓ 7. Tasks marked done")

        # ── 8. Transition execute → verify (all done) ──
        result = engine.transition("verify", reason="Implementation complete")
        assert result["success"] is True
        assert engine.current_state == "verify"
        print("✓ 8. Transition execute → verify succeeds")

        # ── 9. Gate check (fail then pass) ──
        gate_fail = engine.check_gate("All tests pass", passed=False, evidence="2 failures")
        assert gate_fail.passed is False

        result = engine.transition("done")
        assert result["success"] is False, "Should be blocked — gate not passed"
        print("✓ 9. Gate failure blocks transition to done")

        gate_pass = engine.check_gate("All tests pass", passed=True, evidence="42 passed, 0 failed")
        assert gate_pass.passed is True

        result = engine.transition("done", reason="All verified")
        assert result["success"] is True
        assert engine.current_state == "done"
        print("✓ 10. Gate pass allows transition to done")

        # ── 11. Reflections ──
        engine.current_state = "reflect"  # manually set for testing
        r = engine.add_reflection("Testing the reflection system works great")
        assert r.state == "reflect"
        assert len(engine.reflections) == 1
        print("✓ 11. Reflections logged")

        # ── 12. History ──
        assert len(engine.history) == 3  # plan→execute, execute→verify, verify→done
        print(f"✓ 12. History has {len(engine.history)} transitions")

        # ── 13. Persistence ──
        engine2 = WorkflowEngine(workflow_dir)
        assert engine2.current_state == engine.current_state
        assert len(engine2.tasks) == 2
        assert len(engine2.history) == 3
        assert len(engine2.reflections) == 1
        assert len(engine2.gates) == 2
        print("✓ 13. State persisted and reloaded correctly")

        # ── 14. Unblocked transition ──
        available = engine.get_available_transitions()
        # We're at 'reflect' now (manually set), which allows plan, execute, done
        print(f"✓ 14. Available transitions from reflect: {list(available.keys())}")

        print("\n🎉 All tests passed!")

    finally:
        shutil.rmtree(tmpdir)


if __name__ == "__main__":
    test_engine()
