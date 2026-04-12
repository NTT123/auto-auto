"""
Test the full scaffolding flow.

Simulates what the /auto-auto skill would generate, then verifies:
1. Generated workspace structure is correct
2. MCP server starts with WORKFLOW_DIR pointing to generated .workflow/
3. State machine works end-to-end from the generated config
4. .mcp.json is valid
5. .claude/settings.json is valid
"""

import asyncio
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

AUTO_AUTO_DIR = Path(__file__).parent.parent.resolve()


def scaffold_workspace(dest_dir: Path, template_name: str = "iterative-refinement"):
    """Simulate what the /auto-auto skill would generate."""

    # Load template
    template_path = AUTO_AUTO_DIR / "templates" / f"{template_name}.json"
    template = json.loads(template_path.read_text())

    # Customize for this specific task
    template["goal"] = "Build a REST API for user management"

    # Create directory structure
    dest_dir.mkdir(parents=True, exist_ok=True)
    (dest_dir / ".workflow").mkdir()
    (dest_dir / ".claude").mkdir()

    # Write workflow config
    (dest_dir / ".workflow" / "config.json").write_text(
        json.dumps(template, indent=2)
    )

    # Write CLAUDE.md
    (dest_dir / "CLAUDE.md").write_text(
        """# Project: User Management REST API

Build a REST API with CRUD operations for user management.

## Workflow

This project uses the Auto-Auto workflow engine. The MCP provides `wf_*` tools.

**IMPORTANT: Follow this workflow strictly.**

1. Start every session by calling `wf_status()` to see where you are
2. Follow the instructions returned by the current state
3. Use `wf_task()` to create and track tasks
4. Use `wf_transition()` to move between states
5. Use `wf_gate()` to record verification results
6. Use `wf_reflect()` to log reflections

## Key Context

- Tech stack: Python, FastAPI, SQLite
- Must include: Users CRUD, authentication, input validation
- Must have tests

## Success Criteria

- All CRUD endpoints work correctly
- Authentication middleware present
- Test coverage > 80%
- API documentation generated
"""
    )

    # Write workflow.md
    (dest_dir / "workflow.md").write_text(
        """# Workflow: Build User Management REST API

## Pattern: Iterative Refinement

### Why this pattern?
The requirements are clear (CRUD + auth + tests), so we can plan upfront
and iterate. No major unknowns that would require a research phase.

### Phases:
1. **Plan**: Define API endpoints, data models, and test strategy
2. **Execute**: Build the API incrementally
3. **Verify**: Run tests, check all acceptance criteria
4. **Reflect**: What worked? What needs another iteration?

### Success criteria:
- All CRUD endpoints for users (GET, POST, PUT, DELETE)
- JWT authentication
- Input validation with Pydantic
- SQLite persistence
- pytest test suite with >80% coverage
"""
    )

    # Write .mcp.json
    (dest_dir / ".mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "auto-auto": {
                        "type": "stdio",
                        "command": "uv",
                        "args": [
                            "run",
                            "--project",
                            str(AUTO_AUTO_DIR),
                            "python",
                            "-m",
                            "workflow_engine",
                        ],
                        "env": {
                            "WORKFLOW_DIR": str(dest_dir / ".workflow"),
                            "PYTHONPATH": str(AUTO_AUTO_DIR / "src"),
                        },
                    }
                }
            },
            indent=2,
        )
    )

    # Write .claude/settings.json (permissions + Stop/SessionStart hooks)
    hook_command = (
        f"uv run --project {AUTO_AUTO_DIR} python -m workflow_engine.hooks"
    )
    (dest_dir / ".claude" / "settings.json").write_text(
        json.dumps(
            {
                "permissions": {
                    "allow": [
                        "mcp__auto-auto__wf_status",
                        "mcp__auto-auto__wf_state",
                        "mcp__auto-auto__wf_next",
                        "mcp__auto-auto__wf_transition",
                        "mcp__auto-auto__wf_task",
                        "mcp__auto-auto__wf_verify",
                        "mcp__auto-auto__wf_gate",
                        "mcp__auto-auto__wf_reflect",
                        "mcp__auto-auto__wf_loop",
                        "mcp__auto-auto__wf_init",
                    ]
                },
                "hooks": {
                    "Stop": [
                        {
                            "matcher": "",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": f"{hook_command} Stop",
                                }
                            ],
                        }
                    ],
                    "SessionStart": [
                        {
                            "matcher": "startup",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": f"{hook_command} SessionStart",
                                }
                            ],
                        },
                        {
                            "matcher": "resume",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": f"{hook_command} SessionStart",
                                }
                            ],
                        },
                        {
                            "matcher": "compact",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": f"{hook_command} SessionStart",
                                }
                            ],
                        },
                    ],
                },
            },
            indent=2,
        )
    )

    return dest_dir


async def test_scaffold():
    tmpdir = Path(tempfile.mkdtemp())
    dest_dir = tmpdir / "my-api-project"

    try:
        # ── 1. Scaffold ──
        scaffold_workspace(dest_dir)
        print("✓ 1. Workspace scaffolded")

        # ── 2. Verify structure ──
        assert (dest_dir / "CLAUDE.md").exists()
        assert (dest_dir / "workflow.md").exists()
        assert (dest_dir / ".workflow" / "config.json").exists()
        assert (dest_dir / ".mcp.json").exists()
        assert (dest_dir / ".claude" / "settings.json").exists()
        print("✓ 2. All expected files exist")

        # ── 3. Verify JSON files are valid ──
        mcp_config = json.loads((dest_dir / ".mcp.json").read_text())
        assert "mcpServers" in mcp_config
        assert "auto-auto" in mcp_config["mcpServers"]
        print("✓ 3. .mcp.json is valid")

        settings = json.loads((dest_dir / ".claude" / "settings.json").read_text())
        assert "permissions" in settings
        assert len(settings["permissions"]["allow"]) == 10
        # Hooks must be present — they're the enforcement layer
        assert "hooks" in settings, "settings.json must have hooks"
        assert "Stop" in settings["hooks"], "Stop hook must be configured"
        assert "SessionStart" in settings["hooks"], "SessionStart hook must be configured"
        # SessionStart should fire on startup, resume, AND compact for context recovery
        ss_matchers = {entry["matcher"] for entry in settings["hooks"]["SessionStart"]}
        assert {"startup", "resume", "compact"}.issubset(ss_matchers), (
            f"SessionStart should trigger on startup/resume/compact, got {ss_matchers}"
        )
        # Hook commands must use the absolute auto-auto path
        stop_cmd = settings["hooks"]["Stop"][0]["hooks"][0]["command"]
        assert str(AUTO_AUTO_DIR) in stop_cmd, (
            f"Stop hook command must reference absolute auto-auto dir: {stop_cmd}"
        )
        assert "workflow_engine.hooks Stop" in stop_cmd
        print("✓ 4. .claude/settings.json is valid (permissions + Stop + SessionStart hooks)")

        # ── 5. Test MCP engine with generated config ──
        os.environ["WORKFLOW_DIR"] = str(dest_dir / ".workflow")

        import importlib
        import workflow_engine.server as srv
        importlib.reload(srv)

        mcp = srv.mcp

        # wf_status
        result = await mcp.call_tool("wf_status", {})
        data = result.structured_content
        assert data["loaded"] is True
        assert data["current_state"] == "plan"
        assert data["workflow"]["goal"] == "Build a REST API for user management"
        print("✓ 5. MCP engine loads generated workflow config")

        # Create tasks and go through workflow
        await mcp.call_tool("wf_task", {
            "action": "create",
            "name": "Define API endpoints",
        })
        await mcp.call_tool("wf_task", {
            "action": "create",
            "name": "Set up FastAPI project",
        })
        print("✓ 6. Tasks created in generated workspace")

        # Transition
        result = await mcp.call_tool("wf_transition", {
            "to_state": "execute",
            "reason": "Plan ready",
        })
        data = result.structured_content
        assert data["success"] is True
        print("✓ 7. State transition works in generated workspace")

        # Verify state persisted
        state_file = dest_dir / ".workflow" / "state.json"
        assert state_file.exists()
        state_data = json.loads(state_file.read_text())
        assert state_data["current_state"] == "execute"
        assert len(state_data["tasks"]) == 2
        print("✓ 8. State persisted to generated .workflow/state.json")

        # ── 9. Test all templates scaffold correctly ──
        templates_dir = AUTO_AUTO_DIR / "templates"
        for template_file in templates_dir.glob("*.json"):
            template_name = template_file.stem
            test_dir = tmpdir / f"test-{template_name}"
            scaffold_workspace(test_dir, template_name)
            config = json.loads((test_dir / ".workflow" / "config.json").read_text())
            assert "states" in config
            assert "initial_state" in config
            assert config["initial_state"] in config["states"]
            print(f"✓ 9.{template_name}: Template scaffolds correctly")

        # ── 10. End-to-end: scaffolded hooks actually run ──
        # We have a workspace with an in-progress task. The Stop hook
        # should block. The SessionStart hook should inject context.
        import subprocess
        env = {**os.environ, "WORKFLOW_DIR": str(dest_dir / ".workflow")}
        env["PYTHONPATH"] = str(AUTO_AUTO_DIR / "src")

        # Make there be unfinished work so Stop hook blocks
        await mcp.call_tool(
            "wf_task",
            {"action": "update", "task_id": "t1", "status": "in_progress"},
        )

        stop_payload = json.dumps({"cwd": str(dest_dir)})
        stop_proc = subprocess.run(
            [sys.executable, "-m", "workflow_engine.hooks", "Stop"],
            input=stop_payload,
            capture_output=True,
            text=True,
            env=env,
            timeout=10,
        )
        assert stop_proc.returncode == 0, f"Stop hook errored: {stop_proc.stderr}"
        assert stop_proc.stdout, "Stop hook should have produced output (block)"
        stop_response = json.loads(stop_proc.stdout)
        assert stop_response["decision"] == "block"
        assert "Define API endpoints" in stop_response["reason"]  # the in-progress task
        print("✓ 10. Scaffolded Stop hook blocks unilateral exit end-to-end")

        ss_payload = json.dumps({"cwd": str(dest_dir), "source": "startup"})
        ss_proc = subprocess.run(
            [sys.executable, "-m", "workflow_engine.hooks", "SessionStart"],
            input=ss_payload,
            capture_output=True,
            text=True,
            env=env,
            timeout=10,
        )
        assert ss_proc.returncode == 0, f"SessionStart hook errored: {ss_proc.stderr}"
        assert ss_proc.stdout, "SessionStart hook should have produced output"
        ss_response = json.loads(ss_proc.stdout)
        assert ss_response["hookSpecificOutput"]["hookEventName"] == "SessionStart"
        ctx = ss_response["hookSpecificOutput"]["additionalContext"]
        assert "Build a REST API for user management" in ctx
        assert "Define API endpoints" in ctx
        print("✓ 11. Scaffolded SessionStart hook injects context end-to-end")

        print("\n🎉 All scaffold tests passed!")

    finally:
        shutil.rmtree(tmpdir)
        os.environ.pop("WORKFLOW_DIR", None)


if __name__ == "__main__":
    asyncio.run(test_scaffold())
