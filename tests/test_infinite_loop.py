"""
Test the infinite loop mode.

Tests:
- Infinite loops reject verdict='done'
- Infinite loops actively prompt the model to keep going
- Force stop is the only way to terminate an infinite loop
- Safety cap on max_iterations works
- Hints contain ♾️ marker and "DO NOT STOP" guidance
"""

import asyncio
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


SIMPLE_WORKFLOW = {
    "name": "test-infinite",
    "goal": "Test infinite loop mode",
    "initial_state": "work",
    "states": {
        "work": {
            "instruction": "Just work.",
            "transitions": {"done": {}},
        },
        "done": {
            "instruction": "Done.",
            "transitions": {},
        },
    },
}


async def test_infinite_loop():
    tmpdir = Path(tempfile.mkdtemp())
    workflow_dir = tmpdir / ".workflow"
    workflow_dir.mkdir()

    os.environ["WORKFLOW_DIR"] = str(workflow_dir)

    import importlib
    import workflow_engine.server as srv
    importlib.reload(srv)
    mcp = srv.mcp

    try:
        await mcp.call_tool("wf_init", {"config_json": json.dumps(SIMPLE_WORKFLOW)})

        # ── 1. Start infinite loop ──
        result = await mcp.call_tool("wf_loop", {
            "action": "start",
            "focus": "Polish the implementation",
            "mode": "infinite",
        })
        data = result.structured_content
        assert data["started"] is True
        assert data["mode"] == "infinite"
        assert "♾️" in data["hint"] or "INFINITE" in data["hint"]
        assert "DO NOT STOP" in data["hint"]
        print("✓ 1. Infinite loop started with proper warning")

        # ── 2. Try verdict='done' — should be REJECTED ──
        result = await mcp.call_tool("wf_loop", {
            "action": "update",
            "outcome": "Looks good enough",
            "verdict": "done",
        })
        data = result.structured_content
        assert data["done_rejected"] is True
        assert data["loop_complete"] is False
        assert "REJECTED" in data["hint"]
        assert "INFINITE LOOP" in data["hint"]
        # Engine should still be active
        print("✓ 2. verdict='done' is rejected in infinite mode")

        # ── 3. Loop is still active ──
        result = await mcp.call_tool("wf_loop", {"action": "status"})
        data = result.structured_content
        assert data["active"] is True
        assert data["mode"] == "infinite"
        print("✓ 3. Loop is still active after rejected 'done'")

        # ── 4. Continue with next iteration ──
        result = await mcp.call_tool("wf_loop", {
            "action": "next",
            "focus": "Add edge case handling",
        })
        data = result.structured_content
        assert data["iteration"] == 2
        assert data["mode"] == "infinite"
        assert "DO NOT STOP" in data["hint"] or "infinite" in data["hint"].lower()
        print("✓ 4. Next iteration works in infinite mode with strong push")

        # ── 5. Update with continue verdict ──
        result = await mcp.call_tool("wf_loop", {
            "action": "update",
            "improvements": ["handled null inputs"],
            "verdict": "continue",
        })
        data = result.structured_content
        assert data["mode"] == "infinite"
        assert "♾️" in data["hint"] or "INFINITE" in data["hint"]
        assert "Don't stop" in data["hint"] or "keep" in data["hint"].lower()
        print("✓ 5. continue verdict in infinite mode pushes for next iteration")

        # ── 6. Run several more iterations ──
        for i in range(3, 6):
            await mcp.call_tool("wf_loop", {
                "action": "next",
                "focus": f"Improvement {i}",
            })
            await mcp.call_tool("wf_loop", {
                "action": "update",
                "improvements": [f"thing {i}"],
                "verdict": "continue",
            })
        result = await mcp.call_tool("wf_loop", {"action": "status"})
        data = result.structured_content
        assert data["total_iterations"] == 5
        assert data["active"] is True
        print("✓ 6. Ran 5 iterations, still active (no natural stop)")

        # ── 7. Try done again — still rejected ──
        await mcp.call_tool("wf_loop", {
            "action": "next",
            "focus": "Final polish",
        })
        result = await mcp.call_tool("wf_loop", {
            "action": "update",
            "verdict": "done",
        })
        data = result.structured_content
        assert data["done_rejected"] is True
        print("✓ 7. verdict='done' still rejected on iteration 6")

        # ── 8. Force stop — the only way to end infinite loop ──
        result = await mcp.call_tool("wf_loop", {
            "action": "force_stop",
            "reason": "User wants to ship now",
        })
        data = result.structured_content
        assert data["stopped"] is True
        assert data["was_infinite"] is True
        assert data["total_iterations"] == 6
        print("✓ 8. force_stop terminates infinite loop")

        # ── 9. After force_stop, loop is inactive ──
        result = await mcp.call_tool("wf_loop", {"action": "status"})
        data = result.structured_content
        assert data["active"] is False
        assert data["force_stopped"] is True
        print("✓ 9. Loop is inactive after force_stop")

        print("\n--- Infinite loop with safety cap ---\n")

        # ── 10. Reset and try infinite with safety cap ──
        await mcp.call_tool("wf_init", {"config_json": json.dumps(SIMPLE_WORKFLOW)})
        result = await mcp.call_tool("wf_loop", {
            "action": "start",
            "focus": "Test cap",
            "mode": "infinite",
            "max_iterations": 3,
        })
        data = result.structured_content
        assert data["max_iterations"] == 3
        assert "Safety cap: 3" in data["hint"]
        print("✓ 10. Infinite loop with safety cap = 3")

        # ── 11. Run up to the cap ──
        # iteration 1 already started; update + next for 2 and 3
        await mcp.call_tool("wf_loop", {"action": "update", "verdict": "continue"})
        await mcp.call_tool("wf_loop", {"action": "next", "focus": "i2"})
        await mcp.call_tool("wf_loop", {"action": "update", "verdict": "continue"})
        await mcp.call_tool("wf_loop", {"action": "next", "focus": "i3"})
        await mcp.call_tool("wf_loop", {"action": "update", "verdict": "continue"})

        # Try to start iteration 4 — should hit cap
        result = await mcp.call_tool("wf_loop", {"action": "next", "focus": "i4"})
        data = result.structured_content
        assert "error" in data
        assert "Safety cap reached" in data["error"]
        assert data["max_iterations"] == 3
        print("✓ 11. Safety cap blocks iteration beyond limit")

        # ── 12. Status shows max_iterations_reached ──
        result = await mcp.call_tool("wf_loop", {"action": "status"})
        data = result.structured_content
        assert data["max_iterations_reached"] is True
        assert data["total_iterations"] == 3
        print("✓ 12. Status shows safety cap reached")

        # ── 13. Force stop after cap ──
        result = await mcp.call_tool("wf_loop", {
            "action": "force_stop",
            "reason": "Hit safety cap",
        })
        data = result.structured_content
        assert data["stopped"] is True
        print("✓ 13. force_stop works after safety cap reached")

        print("\n--- Bounded mode unchanged ---\n")

        # ── 14. Bounded mode still allows verdict='done' ──
        await mcp.call_tool("wf_init", {"config_json": json.dumps(SIMPLE_WORKFLOW)})
        await mcp.call_tool("wf_loop", {
            "action": "start",
            "focus": "Quick task",
            "mode": "bounded",
        })
        result = await mcp.call_tool("wf_loop", {
            "action": "update",
            "outcome": "Done quickly",
            "verdict": "done",
        })
        data = result.structured_content
        assert data["loop_complete"] is True
        assert "done_rejected" not in data
        print("✓ 14. Bounded mode still allows verdict='done'")

        # ── 15. Default mode is bounded ──
        await mcp.call_tool("wf_init", {"config_json": json.dumps(SIMPLE_WORKFLOW)})
        result = await mcp.call_tool("wf_loop", {
            "action": "start",
            "focus": "Default mode test",
        })
        data = result.structured_content
        assert data["mode"] == "bounded"
        print("✓ 15. Default mode is 'bounded'")

        # ── 16. Persistence of infinite mode ──
        await mcp.call_tool("wf_init", {"config_json": json.dumps(SIMPLE_WORKFLOW)})
        await mcp.call_tool("wf_loop", {
            "action": "start",
            "focus": "Persistence test",
            "mode": "infinite",
        })
        # Reload server
        importlib.reload(srv)
        result = await srv.mcp.call_tool("wf_loop", {"action": "status"})
        data = result.structured_content
        assert data["mode"] == "infinite"
        assert data["active"] is True
        print("✓ 16. Infinite mode persists across reloads")

        print("\n🎉 All infinite loop tests passed!")

    finally:
        shutil.rmtree(tmpdir)
        os.environ.pop("WORKFLOW_DIR", None)


if __name__ == "__main__":
    asyncio.run(test_infinite_loop())
