"""
Test the verification plan system.

Tests: wf_verify tool, pending checks tracking, gate-to-check linkage,
and the full verify-gate-progress loop.
"""

import asyncio
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


WORKFLOW_WITH_VERIFICATION = {
    "name": "test-with-verification",
    "goal": "Test the verification system",
    "pattern": "iterative-refinement",
    "initial_state": "plan",
    "states": {
        "plan": {
            "instruction": "Plan the work.",
            "transitions": {
                "execute": {"requires": ["all_tasks_defined"]}
            },
        },
        "execute": {
            "instruction": "Do the work.",
            "transitions": {
                "verify": {"requires": ["all_tasks_done"]}
            },
        },
        "verify": {
            "instruction": "Verify using the verification plan.",
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
        "strategy": "automated_tests + output_inspection",
        "description": "Run pytest, then check the output report file.",
        "checks": [
            {
                "criteria": "All unit tests pass",
                "method": "automated_tests",
                "how": "Run pytest and check for 0 failures",
                "command": "python -m pytest tests/ -v",
            },
            {
                "criteria": "Integration tests pass",
                "method": "automated_tests",
                "how": "Run integration test suite",
                "command": "python -m pytest tests/integration/ -v",
            },
            {
                "criteria": "Output report is well-formed",
                "method": "output_inspection",
                "how": "Read output/report.json, verify it has required fields",
                "files_to_check": ["output/report.json"],
            },
            {
                "criteria": "No console errors on dashboard",
                "method": "browser_check",
                "how": "Open http://localhost:8000, check Chrome console for errors",
            },
            {
                "criteria": "Code quality review",
                "method": "agent_review",
                "how": "Spawn reviewer agent to check error handling and edge cases",
            },
        ],
    },
}


async def test_verification():
    tmpdir = Path(tempfile.mkdtemp())
    workflow_dir = tmpdir / ".workflow"
    workflow_dir.mkdir()

    os.environ["WORKFLOW_DIR"] = str(workflow_dir)

    import importlib
    import workflow_engine.server as srv
    importlib.reload(srv)
    mcp = srv.mcp

    try:
        # ── 1. Init workflow with verification ──
        result = await mcp.call_tool("wf_init", {
            "config_json": json.dumps(WORKFLOW_WITH_VERIFICATION)
        })
        data = result.structured_content
        assert data["success"] is True
        print("✓ 1. Workflow with verification plan initialized")

        # ── 2. wf_status shows verification summary ──
        result = await mcp.call_tool("wf_status", {})
        data = result.structured_content
        assert data["verification"] is not None
        assert data["verification"]["total_checks"] == 5
        assert data["verification"]["pending_checks"] == 5
        assert data["verification"]["passed_checks"] == 0
        assert data["verification"]["strategy"] == "automated_tests + output_inspection"
        print("✓ 2. wf_status shows verification summary (5 pending, 0 passed)")

        # ── 3. wf_verify shows full plan ──
        result = await mcp.call_tool("wf_verify", {})
        data = result.structured_content
        assert data["has_plan"] is True
        assert data["total_checks"] == 5
        assert len(data["pending"]) == 5
        assert len(data["passed"]) == 0
        assert data["all_passed"] is False

        # Check pending items have the right structure
        first_check = data["pending"][0]
        assert first_check["criteria"] == "All unit tests pass"
        assert first_check["method"] == "automated_tests"
        assert first_check["how"] == "Run pytest and check for 0 failures"
        assert first_check["command"] == "python -m pytest tests/ -v"
        print("✓ 3. wf_verify shows full plan with 5 pending checks")

        # ── 4. Pass first check ──
        result = await mcp.call_tool("wf_gate", {
            "criteria": "All unit tests pass",
            "passed": True,
            "evidence": "pytest: 15 passed, 0 failed in 2.3s",
        })
        data = result.structured_content
        assert data["passed"] is True
        assert data["remaining_checks"] == 4
        assert "4 more check(s) remaining" in data["hint"]
        print("✓ 4. First gate passed, 4 remaining")

        # ── 5. wf_verify shows updated state ──
        result = await mcp.call_tool("wf_verify", {})
        data = result.structured_content
        assert len(data["pending"]) == 4
        assert len(data["passed"]) == 1
        assert data["passed"][0]["criteria"] == "All unit tests pass"
        print("✓ 5. wf_verify reflects the passed check")

        # ── 6. Fail a check ──
        result = await mcp.call_tool("wf_gate", {
            "criteria": "Integration tests pass",
            "passed": False,
            "evidence": "2 failures in test_api.py: 401 on /users endpoint",
        })
        data = result.structured_content
        assert data["passed"] is False
        assert "Fix the issues" in data["hint"]
        # Still 4 remaining because the failed check hasn't passed
        assert data["remaining_checks"] == 4
        print("✓ 6. Failed gate recorded, check still pending")

        # ── 7. Retry and pass the failed check ──
        result = await mcp.call_tool("wf_gate", {
            "criteria": "Integration tests pass",
            "passed": True,
            "evidence": "Fixed auth middleware. pytest: 8 passed, 0 failed",
        })
        data = result.structured_content
        assert data["passed"] is True
        assert data["remaining_checks"] == 3
        print("✓ 7. Retried check now passes, 3 remaining")

        # ── 8. Pass remaining checks ──
        for check_data in [
            ("Output report is well-formed", "report.json has all 5 required fields"),
            ("No console errors on dashboard", "Chrome console: 0 errors, 0 warnings"),
            ("Code quality review", "Reviewer agent: no critical issues found"),
        ]:
            await mcp.call_tool("wf_gate", {
                "criteria": check_data[0],
                "passed": True,
                "evidence": check_data[1],
            })

        result = await mcp.call_tool("wf_verify", {})
        data = result.structured_content
        assert data["all_passed"] is True
        assert len(data["pending"]) == 0
        assert len(data["passed"]) == 5
        assert "All checks passed" in data["hint"]
        print("✓ 8. All 5 checks passed")

        # ── 9. wf_status shows verification complete ──
        result = await mcp.call_tool("wf_status", {})
        data = result.structured_content
        assert data["verification"]["passed_checks"] == 5
        assert data["verification"]["pending_checks"] == 0
        print("✓ 9. wf_status shows all verification complete")

        # ── 10. wf_verify with no plan ──
        # Init a workflow without verification
        await mcp.call_tool("wf_init", {
            "config_json": json.dumps({
                "name": "no-verify", "goal": "", "initial_state": "work",
                "states": {"work": {"instruction": "", "transitions": {}}}
            })
        })
        result = await mcp.call_tool("wf_verify", {})
        data = result.structured_content
        assert data["has_plan"] is False
        assert "No verification plan" in data["message"]
        print("✓ 10. wf_verify handles missing verification plan gracefully")

        print("\n🎉 All verification tests passed!")

    finally:
        shutil.rmtree(tmpdir)
        os.environ.pop("WORKFLOW_DIR", None)


if __name__ == "__main__":
    asyncio.run(test_verification())
