"""
Tests for the auto-auto hook scripts (Stop and SessionStart).

These hooks run as separate processes when Claude Code fires the corresponding
events. We test the hook *logic* directly via stop_hook() and session_start_hook(),
which return (exit_code, stdout_text), and we also subprocess the actual entry
point to verify the wire format end-to-end.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from workflow_engine.engine import WorkflowEngine
from workflow_engine.hooks import (
    _build_context_payload,
    _diagnose_unfinished_work,
    _load_engine,
    _resolve_workflow_dir,
    session_start_hook,
    stop_hook,
)


# ── Test workflow ────────────────────────────────────────────────

TEST_WORKFLOW = {
    "name": "test-hooks-wf",
    "goal": "Validate the hook system",
    "pattern": "iterative-refinement",
    "initial_state": "plan",
    "states": {
        "plan": {
            "instruction": "Make a plan with tasks.",
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
            "instruction": "Check the work.",
            "transitions": {
                "done": {"requires": ["gate_passed"]},
                "execute": {},
            },
        },
        "done": {
            "instruction": "Finished.",
            "transitions": {},
        },
    },
    "verification": {
        "strategy": "automated_tests",
        "description": "Run the test suite.",
        "checks": [
            {
                "criteria": "All unit tests pass",
                "method": "automated_tests",
                "how": "Run pytest",
                "command": "pytest tests/",
            },
            {
                "criteria": "No lint errors",
                "method": "automated_tests",
                "how": "Run ruff",
                "command": "ruff check .",
            },
        ],
    },
}


def _make_workspace() -> Path:
    """Create a tempdir with a fresh workflow config."""
    tmpdir = Path(tempfile.mkdtemp())
    (tmpdir / ".workflow").mkdir()
    (tmpdir / ".workflow" / "config.json").write_text(json.dumps(TEST_WORKFLOW))
    return tmpdir


def _engine_for(tmpdir: Path) -> WorkflowEngine:
    return WorkflowEngine(tmpdir / ".workflow")


# ── _resolve_workflow_dir ────────────────────────────────────────


def test_resolve_workflow_dir_env_takes_precedence():
    os.environ["WORKFLOW_DIR"] = "/env/workflow"
    try:
        path = _resolve_workflow_dir({"cwd": "/cwd"})
        assert path == Path("/env/workflow")
    finally:
        os.environ.pop("WORKFLOW_DIR", None)
    print("✓ resolve_workflow_dir: env var takes precedence")


def test_resolve_workflow_dir_falls_back_to_cwd():
    os.environ.pop("WORKFLOW_DIR", None)
    path = _resolve_workflow_dir({"cwd": "/some/project"})
    assert path == Path("/some/project/.workflow")
    print("✓ resolve_workflow_dir: falls back to cwd")


def test_resolve_workflow_dir_default():
    os.environ.pop("WORKFLOW_DIR", None)
    path = _resolve_workflow_dir({})
    assert path == Path(".workflow")
    print("✓ resolve_workflow_dir: defaults to ./.workflow")


# ── _load_engine ──────────────────────────────────────────────────


def test_load_engine_no_workflow_dir():
    tmpdir = Path(tempfile.mkdtemp())
    try:
        engine = _load_engine(tmpdir / ".workflow")
        assert engine is None
        print("✓ load_engine: returns None when .workflow does not exist")
    finally:
        shutil.rmtree(tmpdir)


def test_load_engine_loads_real_workflow():
    tmpdir = _make_workspace()
    try:
        engine = _load_engine(tmpdir / ".workflow")
        assert engine is not None
        assert engine.is_loaded
        assert engine.config["name"] == "test-hooks-wf"
        print("✓ load_engine: loads a real workflow")
    finally:
        shutil.rmtree(tmpdir)


# ── _build_context_payload ────────────────────────────────────────


def test_build_context_includes_workflow_metadata():
    tmpdir = _make_workspace()
    try:
        engine = _engine_for(tmpdir)
        ctx = _build_context_payload(engine)
        assert "test-hooks-wf" in ctx
        assert "Validate the hook system" in ctx
        assert "plan" in ctx  # current state
        assert "AUTO-AUTO WORKFLOW CONTEXT" in ctx
        print("✓ build_context: includes workflow name, goal, state")
    finally:
        shutil.rmtree(tmpdir)


def test_build_context_includes_pending_tasks():
    tmpdir = _make_workspace()
    try:
        engine = _engine_for(tmpdir)
        engine.create_task("Design API")
        engine.create_task("Write tests")
        ctx = _build_context_payload(engine)
        assert "Design API" in ctx
        assert "Write tests" in ctx
        assert "Pending tasks" in ctx
        print("✓ build_context: includes pending tasks")
    finally:
        shutil.rmtree(tmpdir)


def test_build_context_includes_reflections_and_gates():
    tmpdir = _make_workspace()
    try:
        engine = _engine_for(tmpdir)
        engine.add_reflection("Decided to use FastAPI for speed")
        engine.check_gate("All unit tests pass", passed=True, evidence="42 passed")
        ctx = _build_context_payload(engine)
        assert "FastAPI" in ctx
        assert "All unit tests pass" in ctx
        assert "42 passed" in ctx
        print("✓ build_context: includes reflections and gates")
    finally:
        shutil.rmtree(tmpdir)


def test_build_context_includes_loop_status():
    tmpdir = _make_workspace()
    try:
        engine = _engine_for(tmpdir)
        engine.start_loop(focus="Polish error messages", mode="infinite")
        ctx = _build_context_payload(engine)
        assert "Loop:" in ctx
        assert "infinite" in ctx
        assert "Polish error messages" in ctx
        print("✓ build_context: includes loop status with mode and focus")
    finally:
        shutil.rmtree(tmpdir)


# ── _diagnose_unfinished_work ─────────────────────────────────────


def test_diagnose_done_state_allows_stop():
    tmpdir = _make_workspace()
    try:
        engine = _engine_for(tmpdir)
        engine.current_state = "done"
        reasons = _diagnose_unfinished_work(engine)
        assert reasons == []
        print("✓ diagnose: 'done' state always allows stop")
    finally:
        shutil.rmtree(tmpdir)


def test_diagnose_blocks_on_in_progress_task():
    tmpdir = _make_workspace()
    try:
        engine = _engine_for(tmpdir)
        engine.create_task("Design API")
        engine.update_task("t1", status="in_progress")
        reasons = _diagnose_unfinished_work(engine)
        assert len(reasons) >= 1
        assert any("IN-PROGRESS" in r for r in reasons)
        assert any("Design API" in r for r in reasons)
        print("✓ diagnose: blocks when a task is in_progress")
    finally:
        shutil.rmtree(tmpdir)


def test_diagnose_blocks_on_pending_in_execute():
    tmpdir = _make_workspace()
    try:
        engine = _engine_for(tmpdir)
        # Create tasks, transition to execute, but don't start them
        engine.create_task("Design API")
        engine.create_task("Write tests")
        engine.transition("execute", reason="ready")
        reasons = _diagnose_unfinished_work(engine)
        assert len(reasons) >= 1
        assert any("PENDING" in r for r in reasons)
        print("✓ diagnose: blocks when execute has pending tasks")
    finally:
        shutil.rmtree(tmpdir)


def test_diagnose_blocks_on_pending_verify_checks():
    tmpdir = _make_workspace()
    try:
        engine = _engine_for(tmpdir)
        # Get to verify state with no gates passed
        engine.create_task("Design")
        engine.transition("execute", reason="plan done")
        engine.update_task("t1", status="done")
        engine.transition("verify", reason="execute done")
        reasons = _diagnose_unfinished_work(engine)
        assert len(reasons) >= 1
        # The verification plan has 2 checks; both pending
        assert any("verification" in r.lower() for r in reasons)
        print("✓ diagnose: blocks when verify state has pending checks")
    finally:
        shutil.rmtree(tmpdir)


def test_diagnose_blocks_on_active_infinite_loop():
    tmpdir = _make_workspace()
    try:
        engine = _engine_for(tmpdir)
        engine.start_loop(focus="Polish", mode="infinite")
        reasons = _diagnose_unfinished_work(engine)
        assert len(reasons) >= 1
        assert any("INFINITE" in r for r in reasons)
        print("✓ diagnose: blocks when an infinite loop is active")
    finally:
        shutil.rmtree(tmpdir)


def test_diagnose_force_stopped_infinite_loop_does_not_block():
    tmpdir = _make_workspace()
    try:
        engine = _engine_for(tmpdir)
        engine.start_loop(focus="Polish", mode="infinite")
        engine.force_stop_loop(reason="user wants to ship")
        reasons = _diagnose_unfinished_work(engine)
        # No more loop block (it's force-stopped), no other unfinished work
        assert all("INFINITE" not in r for r in reasons)
        print("✓ diagnose: force-stopped infinite loop no longer blocks")
    finally:
        shutil.rmtree(tmpdir)


def test_diagnose_clean_plan_state_allows_stop():
    """In 'plan' with no in-progress work, stopping is OK (waiting for input)."""
    tmpdir = _make_workspace()
    try:
        engine = _engine_for(tmpdir)
        # Just loaded, current_state == "plan", no tasks yet
        reasons = _diagnose_unfinished_work(engine)
        assert reasons == []
        print("✓ diagnose: clean plan state allows stop")
    finally:
        shutil.rmtree(tmpdir)


def test_diagnose_custom_workflow_state_names():
    """A custom workflow with non-standard state names should still get
    the right work-state and verify-state classification dynamically.

    This uses a workflow with states named 'build' and 'qa' instead of the
    standard 'execute' and 'verify' — but they still have the same
    requirements (all_tasks_done, gate_passed). The hook should handle them.
    """
    tmpdir = Path(tempfile.mkdtemp())
    try:
        (tmpdir / ".workflow").mkdir()
        custom_wf = {
            "name": "custom-naming",
            "goal": "Test dynamic state classification",
            "initial_state": "draft",
            "states": {
                "draft": {
                    "instruction": "Plan it.",
                    "transitions": {"build": {"requires": ["all_tasks_defined"]}},
                },
                "build": {  # not literally named "execute"
                    "instruction": "Build it.",
                    "transitions": {"qa": {"requires": ["all_tasks_done"]}},
                },
                "qa": {  # not literally named "verify"
                    "instruction": "Test it.",
                    "transitions": {"done": {"requires": ["gate_passed"]}},
                },
                "done": {"instruction": "Done.", "transitions": {}},
            },
            "verification": {
                "strategy": "automated_tests",
                "checks": [{"criteria": "Tests pass", "method": "automated_tests"}],
            },
        }
        (tmpdir / ".workflow" / "config.json").write_text(json.dumps(custom_wf))

        engine = WorkflowEngine(tmpdir / ".workflow")

        # In "build" with pending tasks → should block (custom name still detected)
        engine.create_task("Implement thing")
        engine.transition("build", reason="ready")
        reasons = _diagnose_unfinished_work(engine)
        assert any("PENDING" in r for r in reasons), (
            f"Custom 'build' state should be classified as work-state, got: {reasons}"
        )

        # Finish the task, transition to "qa" → should block on pending checks
        engine.update_task("t1", status="done")
        engine.transition("qa", reason="built")
        reasons = _diagnose_unfinished_work(engine)
        assert any("verification" in r.lower() for r in reasons), (
            f"Custom 'qa' state should be classified as verify-state, got: {reasons}"
        )

        print("✓ diagnose: dynamically classifies custom state names")
    finally:
        shutil.rmtree(tmpdir)


# ── stop_hook ────────────────────────────────────────────────────


def test_stop_hook_no_workflow_allows():
    tmpdir = Path(tempfile.mkdtemp())
    try:
        os.environ.pop("WORKFLOW_DIR", None)
        code, out = stop_hook({"cwd": str(tmpdir)})
        assert code == 0
        assert out == ""
        print("✓ stop_hook: no workflow → allow stop, no output")
    finally:
        shutil.rmtree(tmpdir)


def test_stop_hook_done_state_allows():
    tmpdir = _make_workspace()
    try:
        engine = _engine_for(tmpdir)
        engine.current_state = "done"
        engine._save()

        os.environ.pop("WORKFLOW_DIR", None)
        code, out = stop_hook({"cwd": str(tmpdir)})
        assert code == 0
        assert out == ""
        print("✓ stop_hook: done state → allow stop")
    finally:
        shutil.rmtree(tmpdir)


def test_stop_hook_blocks_with_decision_block():
    tmpdir = _make_workspace()
    try:
        engine = _engine_for(tmpdir)
        engine.create_task("Important work")
        engine.update_task("t1", status="in_progress")
        engine._save()

        os.environ.pop("WORKFLOW_DIR", None)
        code, out = stop_hook({"cwd": str(tmpdir)})
        assert code == 0
        assert out, "Stop hook should have produced output"

        response = json.loads(out)
        assert response["decision"] == "block"
        assert "Important work" in response["reason"]
        assert "STOP BLOCKED" in response["reason"]
        # Block message should also include context payload
        assert "AUTO-AUTO WORKFLOW CONTEXT" in response["reason"]
        print("✓ stop_hook: blocks with decision=block and full reason")
    finally:
        shutil.rmtree(tmpdir)


def test_stop_hook_uses_env_var_workflow_dir():
    tmpdir = _make_workspace()
    try:
        engine = _engine_for(tmpdir)
        engine.create_task("Stuff")
        engine.update_task("t1", status="in_progress")
        engine._save()

        os.environ["WORKFLOW_DIR"] = str(tmpdir / ".workflow")
        try:
            code, out = stop_hook({})  # No cwd in payload
            assert code == 0
            assert out
            response = json.loads(out)
            assert response["decision"] == "block"
            print("✓ stop_hook: uses WORKFLOW_DIR env var when cwd absent")
        finally:
            os.environ.pop("WORKFLOW_DIR", None)
    finally:
        shutil.rmtree(tmpdir)


# ── session_start_hook ───────────────────────────────────────────


def test_session_start_hook_no_workflow_silent():
    tmpdir = Path(tempfile.mkdtemp())
    try:
        os.environ.pop("WORKFLOW_DIR", None)
        code, out = session_start_hook({"cwd": str(tmpdir)})
        assert code == 0
        assert out == ""
        print("✓ session_start_hook: no workflow → no output")
    finally:
        shutil.rmtree(tmpdir)


def test_session_start_hook_injects_context():
    tmpdir = _make_workspace()
    try:
        engine = _engine_for(tmpdir)
        engine.create_task("Important task")
        engine.add_reflection("We chose FastAPI")
        engine._save()

        os.environ.pop("WORKFLOW_DIR", None)
        code, out = session_start_hook({"cwd": str(tmpdir)})
        assert code == 0
        assert out

        response = json.loads(out)
        hso = response["hookSpecificOutput"]
        assert hso["hookEventName"] == "SessionStart"
        ctx = hso["additionalContext"]
        assert "test-hooks-wf" in ctx
        assert "Validate the hook system" in ctx
        assert "Important task" in ctx
        assert "FastAPI" in ctx
        print("✓ session_start_hook: injects rich context payload")
    finally:
        shutil.rmtree(tmpdir)


# ── Subprocess wire-format tests ──────────────────────────────────


def test_stop_hook_subprocess_wire_format():
    """Run the actual `python -m workflow_engine.hooks Stop` entry point."""
    tmpdir = _make_workspace()
    try:
        engine = _engine_for(tmpdir)
        engine.create_task("Real task")
        engine.update_task("t1", status="in_progress")
        engine._save()

        repo_root = Path(__file__).parent.parent
        env = {**os.environ, "WORKFLOW_DIR": str(tmpdir / ".workflow")}
        env.pop("PYTHONPATH", None)
        env["PYTHONPATH"] = str(repo_root / "src")

        payload = json.dumps({"cwd": str(tmpdir), "hook_event_name": "Stop"})
        proc = subprocess.run(
            [sys.executable, "-m", "workflow_engine.hooks", "Stop"],
            input=payload,
            capture_output=True,
            text=True,
            env=env,
            timeout=10,
        )
        assert proc.returncode == 0, f"stderr: {proc.stderr}"
        assert proc.stdout, "Expected JSON output"
        response = json.loads(proc.stdout)
        assert response["decision"] == "block"
        print("✓ stop_hook subprocess: wire format works end-to-end")
    finally:
        shutil.rmtree(tmpdir)


def test_session_start_hook_subprocess_wire_format():
    """Run the actual `python -m workflow_engine.hooks SessionStart` entry point."""
    tmpdir = _make_workspace()
    try:
        engine = _engine_for(tmpdir)
        engine.create_task("Real task")
        engine._save()

        repo_root = Path(__file__).parent.parent
        env = {**os.environ, "WORKFLOW_DIR": str(tmpdir / ".workflow")}
        env.pop("PYTHONPATH", None)
        env["PYTHONPATH"] = str(repo_root / "src")

        payload = json.dumps(
            {
                "cwd": str(tmpdir),
                "hook_event_name": "SessionStart",
                "source": "startup",
            }
        )
        proc = subprocess.run(
            [sys.executable, "-m", "workflow_engine.hooks", "SessionStart"],
            input=payload,
            capture_output=True,
            text=True,
            env=env,
            timeout=10,
        )
        assert proc.returncode == 0, f"stderr: {proc.stderr}"
        assert proc.stdout, "Expected JSON output"
        response = json.loads(proc.stdout)
        assert response["hookSpecificOutput"]["hookEventName"] == "SessionStart"
        assert "Real task" in response["hookSpecificOutput"]["additionalContext"]
        print("✓ session_start_hook subprocess: wire format works end-to-end")
    finally:
        shutil.rmtree(tmpdir)


def test_unknown_hook_subprocess_does_not_crash_user():
    """An unknown hook name should fail gracefully — exit 0, message to stderr."""
    repo_root = Path(__file__).parent.parent
    env = {**os.environ}
    env.pop("PYTHONPATH", None)
    env["PYTHONPATH"] = str(repo_root / "src")

    proc = subprocess.run(
        [sys.executable, "-m", "workflow_engine.hooks", "WrongHook"],
        input="{}",
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )
    # Failsafe: even an unknown hook should exit 0 (don't trap the user)
    assert proc.returncode == 0
    assert "Unknown hook" in proc.stderr
    print("✓ unknown hook: failsafe — exit 0, error to stderr")


# ── Test runner ──────────────────────────────────────────────────


def main():
    tests = [
        test_resolve_workflow_dir_env_takes_precedence,
        test_resolve_workflow_dir_falls_back_to_cwd,
        test_resolve_workflow_dir_default,
        test_load_engine_no_workflow_dir,
        test_load_engine_loads_real_workflow,
        test_build_context_includes_workflow_metadata,
        test_build_context_includes_pending_tasks,
        test_build_context_includes_reflections_and_gates,
        test_build_context_includes_loop_status,
        test_diagnose_done_state_allows_stop,
        test_diagnose_blocks_on_in_progress_task,
        test_diagnose_blocks_on_pending_in_execute,
        test_diagnose_blocks_on_pending_verify_checks,
        test_diagnose_blocks_on_active_infinite_loop,
        test_diagnose_force_stopped_infinite_loop_does_not_block,
        test_diagnose_clean_plan_state_allows_stop,
        test_diagnose_custom_workflow_state_names,
        test_stop_hook_no_workflow_allows,
        test_stop_hook_done_state_allows,
        test_stop_hook_blocks_with_decision_block,
        test_stop_hook_uses_env_var_workflow_dir,
        test_session_start_hook_no_workflow_silent,
        test_session_start_hook_injects_context,
        test_stop_hook_subprocess_wire_format,
        test_session_start_hook_subprocess_wire_format,
        test_unknown_hook_subprocess_does_not_crash_user,
    ]

    failed = 0
    for t in tests:
        try:
            t()
        except AssertionError as e:
            print(f"✗ {t.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"✗ {t.__name__}: unexpected error: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    if failed == 0:
        print(f"\n🎉 All {len(tests)} hook tests passed!")
    else:
        print(f"\n❌ {failed} of {len(tests)} hook tests failed.")
        sys.exit(1)


if __name__ == "__main__":
    main()
