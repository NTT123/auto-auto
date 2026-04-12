"""
Workflow Engine MCP Server.

Exposes the workflow state machine as MCP tools that guide Claude Code
through structured problem-solving workflows.

Usage:
    uv run python -m workflow_engine.server
    # or
    fastmcp run src/workflow_engine/server.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from fastmcp import FastMCP

from workflow_engine.engine import WorkflowEngine

# ── Configuration ────────────────────────────────────────────────
# The workflow directory defaults to .workflow/ in the current working directory.
# Override with WORKFLOW_DIR env var.
WORKFLOW_DIR = Path(os.environ.get("WORKFLOW_DIR", ".workflow"))

# ── Server setup ─────────────────────────────────────────────────
mcp = FastMCP(
    "auto-auto",
    instructions=(
        "Auto-Auto: A workflow state-machine engine that guides you through "
        "structured problem-solving workflows. Call wf_status() first to see "
        "where you are. Follow the workflow — it keeps you on track."
    ),
)

engine = WorkflowEngine(WORKFLOW_DIR)


# ── Helper ───────────────────────────────────────────────────────

def _ensure_loaded() -> dict | None:
    """Reload config and check if a workflow is loaded. Returns error dict or None."""
    engine.reload_config()
    if not engine.is_loaded:
        return {
            "error": "No workflow loaded",
            "hint": (
                "Use the /workflow skill to design a workflow for your task, "
                "or manually create .workflow/config.json with a workflow definition."
            ),
        }
    return None


# ── MCP Tools ────────────────────────────────────────────────────


@mcp.tool()
def wf_status() -> dict:
    """
    Get the full workflow dashboard.

    Shows: workflow name/goal, current state, instructions for what to do now,
    tasks in this state, available transitions (and what blocks them),
    recent reflections, and overall progress.

    Call this FIRST when starting work to understand where you are.
    Call this AFTER each transition to get your new instructions.
    """
    err = _ensure_loaded()
    if err:
        return err
    return engine.get_full_status()


@mcp.tool()
def wf_state() -> dict:
    """
    Get focused details about the current state.

    Returns: state name, instruction (what you should do), tasks in this state,
    and what transitions are available. Lighter than wf_status().
    """
    err = _ensure_loaded()
    if err:
        return err

    state_def = engine.get_state_def()
    state_tasks = engine._get_state_tasks(engine.current_state)

    return {
        "state": engine.current_state,
        "instruction": state_def.get("instruction", ""),
        "tasks": [t.to_dict() for t in state_tasks],
        "available_transitions": list(engine.get_available_transitions().keys()),
    }


@mcp.tool()
def wf_next() -> dict:
    """
    Show what transitions are available and what's required for each.

    Use this to understand what you need to do before you can move forward.
    """
    err = _ensure_loaded()
    if err:
        return err

    transitions = engine.get_available_transitions()
    result = {}
    for t_name, t_def in transitions.items():
        allowed, reasons = engine.check_transition_requirements(t_name)
        target_def = engine.get_state_def(t_name)
        result[t_name] = {
            "allowed": allowed,
            "blockers": reasons if not allowed else [],
            "requires": t_def.get("requires", []),
            "target_instruction_preview": target_def.get("instruction", "")[:100],
        }
    return {"current_state": engine.current_state, "transitions": result}


@mcp.tool()
def wf_transition(to_state: str, reason: str = "") -> dict:
    """
    Transition to a new workflow state.

    This will be BLOCKED if preconditions aren't met (e.g., tasks not done,
    gate not passed). Check wf_next() to see what's needed.

    Args:
        to_state: The state to transition to (e.g., "execute", "verify", "reflect")
        reason: Why you're making this transition (logged in history)
    """
    err = _ensure_loaded()
    if err:
        return err
    return engine.transition(to_state, reason)


@mcp.tool()
def wf_task(
    action: str,
    name: str = "",
    description: str = "",
    task_id: str = "",
    status: str = "",
    state: str = "",
    parent_id: str = "",
) -> dict:
    """
    Manage tasks within the workflow.

    Actions:
      - "create": Create a new task (provide name, description, optionally state and parent_id)
      - "update": Update a task (provide task_id and any of: status, name, description)
        Valid statuses: pending, in_progress, done, blocked
      - "list": List tasks (optionally filter by state and/or status)
      - "done": Mark a task as done (shortcut: provide task_id)

    Args:
        action: One of "create", "update", "list", "done"
        name: Task name (for create)
        description: Task description (for create/update)
        task_id: Task ID like "t1" (for update/done)
        status: New status (for update): pending, in_progress, done, blocked
        state: Filter by workflow state (for list), or assign to state (for create)
        parent_id: Parent task ID for subtasks (for create)
    """
    err = _ensure_loaded()
    if err:
        return err

    if action == "create":
        if not name:
            return {"error": "Task name is required for 'create'"}
        task = engine.create_task(
            name=name,
            description=description,
            state=state or None,
            parent_id=parent_id or None,
        )
        return {"created": task.to_dict()}

    elif action == "update":
        if not task_id:
            return {"error": "task_id is required for 'update'"}
        try:
            task = engine.update_task(
                task_id=task_id,
                status=status or None,
                name=name or None,
                description=description or None,
            )
            return {"updated": task.to_dict()}
        except ValueError as e:
            return {"error": str(e)}

    elif action == "done":
        if not task_id:
            return {"error": "task_id is required for 'done'"}
        try:
            task = engine.update_task(task_id=task_id, status="done")
            return {"updated": task.to_dict(), "message": f"Task '{task.name}' marked done"}
        except ValueError as e:
            return {"error": str(e)}

    elif action == "list":
        tasks = engine.list_tasks(
            state=state or None,
            status=status or None,
        )
        return {
            "count": len(tasks),
            "tasks": [t.to_dict() for t in tasks],
        }

    else:
        return {"error": f"Unknown action '{action}'. Use: create, update, done, list"}


@mcp.tool()
def wf_verify() -> dict:
    """
    Get the verification plan: what to check, how to check it, and what's left.

    The verification plan is designed during workflow scaffolding and tells you
    EXACTLY how to verify the work — no guessing. Strategies are ranked from
    most to least automated:

    1. automated_tests  — Run test suites. Best: fast, repeatable, objective.
    2. output_inspection — Read/examine output files (text, images, PDFs, logs).
    3. browser_check     — Use Chrome DevTools / browser automation to inspect pages.
    4. agent_review      — Spawn a separate Claude Code instance to review.
    5. user_review       — Ask the user. LAST RESORT only (bottleneck).

    Call this when entering a verify state. Work through each pending check,
    then record results with wf_gate().
    """
    err = _ensure_loaded()
    if err:
        return err

    plan = engine.get_verification_plan()
    if not plan:
        return {
            "has_plan": False,
            "message": (
                "No verification plan defined in the workflow config. "
                "You should still verify your work — run tests, check outputs, "
                "and record results with wf_gate(). But there's no structured plan "
                "to follow. Consider adding a 'verification' section to config.json."
            ),
        }

    pending = engine.get_pending_checks()
    all_checks = plan.get("checks", [])

    # Find passed checks
    passed_criteria = {g.criteria for g in engine.gates if g.passed}
    passed_checks = [c for c in all_checks if c.get("criteria") in passed_criteria]

    return {
        "has_plan": True,
        "strategy": plan.get("strategy", ""),
        "strategy_description": plan.get("description", ""),
        "total_checks": len(all_checks),
        "passed": [
            {"criteria": c["criteria"], "method": c.get("method", "")}
            for c in passed_checks
        ],
        "pending": [
            {
                "criteria": c["criteria"],
                "method": c.get("method", ""),
                "how": c.get("how", ""),
                "command": c.get("command", ""),
                "files_to_check": c.get("files_to_check", []),
            }
            for c in pending
        ],
        "all_passed": len(pending) == 0,
        "hint": (
            "Work through each pending check. For each one, execute the verification "
            "as described in 'how', then record the result with wf_gate(criteria=..., "
            "passed=True/False, evidence='...'). Be honest — failed checks help you "
            "find real issues."
        ) if pending else "All checks passed! You can proceed.",
    }


@mcp.tool()
def wf_gate(criteria: str, passed: bool, evidence: str) -> dict:
    """
    Record a verification gate check result.

    After performing a verification (see wf_verify for what to check),
    record whether it passed or failed with concrete evidence.

    Be HONEST. The point is to catch issues early, not rubber-stamp progress.

    Args:
        criteria: What was checked — should match a check from wf_verify()
                  (e.g., "All unit tests pass", "Homepage renders correctly")
        passed: Whether the criteria was met (true/false)
        evidence: Concrete evidence (e.g., "pytest: 42 passed, 0 failed",
                  "Screenshot shows broken layout on mobile")
    """
    err = _ensure_loaded()
    if err:
        return err

    gate = engine.check_gate(criteria=criteria, passed=passed, evidence=evidence)
    result = gate.to_dict()

    # Show remaining checks after recording
    pending = engine.get_pending_checks()
    result["remaining_checks"] = len(pending)

    if not passed:
        result["hint"] = (
            "Gate did not pass. Fix the issues, then re-run the check. "
            "Use wf_reflect() to log what went wrong if you need to think through it."
        )
    elif pending:
        result["hint"] = (
            f"{len(pending)} more check(s) remaining. "
            "Call wf_verify() to see what's next."
        )
    else:
        result["hint"] = "All verification checks passed! You can transition forward."

    return result


@mcp.tool()
def wf_reflect(content: str) -> dict:
    """
    Log a reflection about the current state.

    Reflections capture: what you learned, what worked, what didn't, what to do
    differently. They're persisted and fed into future context.

    Use this liberally — reflections are what make the next iteration better.

    Args:
        content: Your reflection (be specific and actionable)
    """
    err = _ensure_loaded()
    if err:
        return err

    reflection = engine.add_reflection(content=content)
    return {
        "logged": reflection.to_dict(),
        "total_reflections": len(engine.reflections),
    }


@mcp.tool()
def wf_loop(
    action: str,
    focus: str = "",
    outcome: str = "",
    improvements: list[str] | None = None,
    remaining_issues: list[str] | None = None,
    verdict: str = "",
    mode: str = "bounded",
    max_iterations: int = 0,
    reason: str = "",
) -> dict:
    """
    Manage the improvement loop — the core pattern for iterative refinement.

    The loop pattern: once you have a working v1, enter a loop to keep improving.
    Each iteration: EVALUATE what to improve → IMPROVE it → VERIFY → REFLECT → decide.

    LOOP MODES:
      - "bounded"  (default): Model decides when to stop with verdict='done'.
      - "infinite": Model is PUSHED to keep going. verdict='done' is REJECTED.
                    Only an explicit force_stop terminates the loop.
                    Use this when you want continuous improvement and don't trust
                    the model to know when to stop. Optional max_iterations as a
                    safety cap.

    Actions:
      - "start":  Begin a loop. Provide 'focus' (what this iteration improves)
                   and optionally 'mode' ("bounded" or "infinite") and 'max_iterations'.
      - "next":   Start the next iteration. Provide 'focus' for the new iteration.
      - "update": Record iteration results. Provide any of:
                   outcome, improvements, remaining_issues, verdict.
                   verdict: "continue" (more iterations) or "done" (stop).
                   In INFINITE mode, "done" is silently rewritten to "continue".
      - "status": Get full loop status: mode, iteration count, history, convergence.
      - "force_stop": Explicitly terminate any loop, including infinite ones.
                   Provide 'reason'. Use sparingly — defeats the purpose of infinite mode.

    Args:
        action: One of "start", "next", "update", "status", "force_stop"
        focus: What this iteration aims to improve (for start/next)
        outcome: What actually happened (for update)
        improvements: Concrete things that got better (for update)
        remaining_issues: Things still to fix (for update)
        verdict: "continue" or "done" (for update)
        mode: "bounded" or "infinite" (for start)
        max_iterations: Safety cap (0 = unlimited; for start)
        reason: Why force-stopping (for force_stop)
    """
    err = _ensure_loaded()
    if err:
        return err

    if action == "start":
        if not focus:
            return {"error": "Provide 'focus': what should this iteration improve?"}
        if mode not in ("bounded", "infinite"):
            return {"error": "mode must be 'bounded' or 'infinite'"}

        try:
            iteration = engine.start_loop(focus, mode=mode, max_iterations=max_iterations)
        except ValueError as e:
            return {"error": str(e)}

        if mode == "infinite":
            hint = (
                f"♾️ INFINITE LOOP STARTED (iteration {iteration.iteration}). "
                f"Focus: {focus}. "
                f"DO NOT STOP. Keep iterating until force-stopped. "
                f"Even when things look 'good enough', there's always more to improve. "
                f"Work on this iteration, then call wf_loop(action='update', ...) with results, "
                f"then wf_loop(action='next', focus='...') to continue."
            )
            if max_iterations:
                hint += f" Safety cap: {max_iterations} iterations max."
        else:
            hint = (
                f"Loop started (iteration {iteration.iteration}). "
                "Work on the improvements, then call wf_loop(action='update', ...) "
                "with your results."
            )

        return {
            "started": True,
            "mode": mode,
            "iteration": iteration.iteration,
            "focus": iteration.focus,
            "entry_state": engine.loop_entry_state,
            "max_iterations": max_iterations,
            "hint": hint,
        }

    elif action == "next":
        if not focus:
            return {"error": "Provide 'focus': what should the next iteration improve?"}
        if not engine.loop_active and not engine.iterations:
            return {"error": "No loop active. Use action='start' first."}
        # Check if previous iteration was closed
        if engine.iterations and not engine.iterations[-1].verdict:
            return {
                "error": "Current iteration not closed yet. "
                "Call wf_loop(action='update', verdict='continue') first.",
            }

        # Check safety cap
        if (
            engine.loop_max_iterations > 0
            and len(engine.iterations) >= engine.loop_max_iterations
        ):
            return {
                "error": (
                    f"Safety cap reached: {engine.loop_max_iterations} iterations. "
                    f"Use action='force_stop' to terminate, or run wf_loop(action='status') "
                    f"to see what happened."
                ),
                "max_iterations": engine.loop_max_iterations,
                "current_iteration": len(engine.iterations),
            }

        iteration = engine.next_iteration(focus)

        if engine.loop_mode == "infinite":
            hint = (
                f"♾️ INFINITE LOOP — Iteration {iteration.iteration}. Focus: {focus}. "
                f"DO NOT STOP. Even if you think the work is done, there is always something "
                f"to improve: edge cases, performance, code quality, error handling, "
                f"documentation, tests. Keep going."
            )
        else:
            hint = (
                f"Iteration {iteration.iteration} started. Focus: {focus}. "
                "Work on the improvements, verify, then update."
            )

        return {
            "iteration": iteration.iteration,
            "mode": engine.loop_mode,
            "focus": iteration.focus,
            "hint": hint,
        }

    elif action == "update":
        if not engine.iterations:
            return {"error": "No active iteration. Use action='start' first."}
        if verdict and verdict not in ("continue", "done"):
            return {"error": "verdict must be 'continue' or 'done'"}

        # Capture mode-related info before update
        was_infinite = engine.loop_mode == "infinite"

        iteration, accepted_done = engine.update_iteration(
            outcome=outcome,
            improvements=improvements,
            remaining_issues=remaining_issues,
            verdict=verdict,
        )

        result = {
            "iteration": iteration.iteration,
            "mode": engine.loop_mode,
            "updated": True,
        }

        if verdict == "done" and not accepted_done and was_infinite:
            # Infinite loop rejected the "done" verdict
            result["done_rejected"] = True
            result["loop_complete"] = False
            result["hint"] = (
                f"♾️ INFINITE LOOP — verdict='done' was REJECTED. "
                f"This is an infinite loop; you cannot stop it with 'done'. "
                f"Your iteration was closed with verdict='continue' instead. "
                f"Call wf_loop(action='next', focus='...') to start iteration "
                f"{iteration.iteration + 1}. Even if it feels done, there is always "
                f"more to improve. Some ideas: harder edge cases, performance "
                f"optimization, better error messages, more tests, refactoring, "
                f"documentation, accessibility, polish. Pick something and keep going. "
                f"Only an explicit wf_loop(action='force_stop', reason='...') can end this loop."
            )
        elif verdict == "done" and accepted_done:
            result["loop_complete"] = True
            result["total_iterations"] = len(engine.iterations)
            result["hint"] = (
                f"Loop complete after {len(engine.iterations)} iterations. "
                "You can now transition to 'done' or continue with the workflow."
            )
        elif verdict == "continue":
            if was_infinite:
                result["hint"] = (
                    f"♾️ Iteration closed. INFINITE LOOP continues. "
                    f"Call wf_loop(action='next', focus='...') for iteration "
                    f"{iteration.iteration + 1}. Don't stop — keep improving."
                )
            else:
                result["hint"] = (
                    "Iteration closed. Call wf_loop(action='next', focus='...') "
                    "to start the next iteration."
                )
        else:
            if was_infinite:
                result["hint"] = (
                    "♾️ Iteration updated. INFINITE LOOP active — set verdict='continue' "
                    "to close this iteration and start the next one. "
                    "(verdict='done' will be rejected.)"
                )
            else:
                result["hint"] = (
                    "Iteration updated. When ready, set verdict='continue' or 'done'."
                )
        if remaining_issues:
            result["remaining_issues"] = remaining_issues
        return result

    elif action == "force_stop":
        result = engine.force_stop_loop(reason=reason)
        if result.get("stopped"):
            if result.get("was_infinite"):
                result["hint"] = (
                    f"♾️ Infinite loop force-stopped after {result['total_iterations']} "
                    f"iterations. Reason: {reason or '(none)'}. "
                    f"You can now transition to a different state or call wf_loop(action='start', ...) "
                    f"to begin a new loop."
                )
            else:
                result["hint"] = (
                    f"Loop stopped after {result['total_iterations']} iterations."
                )
        return result

    elif action == "status":
        return engine.get_loop_status()

    else:
        return {"error": f"Unknown action '{action}'. Use: start, next, update, status"}


@mcp.tool()
def wf_init(config_json: str) -> dict:
    """
    Initialize or reset a workflow from a JSON config string.

    This is an alternative to having the /workflow skill write the config file.
    You can call this directly to set up a workflow programmatically.

    The config must have: name, goal, states (with instructions and transitions),
    and initial_state.

    Args:
        config_json: JSON string with the workflow definition
    """
    try:
        config = json.loads(config_json)
    except json.JSONDecodeError as e:
        return {"error": f"Invalid JSON: {e}"}

    # Validate required fields
    required = ["name", "states", "initial_state"]
    missing = [f for f in required if f not in config]
    if missing:
        return {"error": f"Missing required fields: {missing}"}

    if config["initial_state"] not in config["states"]:
        return {
            "error": f"initial_state '{config['initial_state']}' not found in states"
        }

    # Write config and reset state
    engine.workflow_dir.mkdir(parents=True, exist_ok=True)
    engine.config_path.write_text(json.dumps(config, indent=2))

    # Clear old state
    if engine.state_path.exists():
        engine.state_path.unlink()

    # Reload
    engine.config = {}
    engine.current_state = ""
    engine.tasks = {}
    engine.gates = []
    engine.reflections = []
    engine.history = []
    engine._task_counter = 0
    engine.loop_active = False
    engine.loop_mode = "bounded"
    engine.loop_entry_state = ""
    engine.loop_max_iterations = 0
    engine.loop_force_stopped = False
    engine.iterations = []
    engine._load()
    engine._save()

    return {
        "success": True,
        "workflow": config.get("name", "unnamed"),
        "goal": config.get("goal", ""),
        "initial_state": config["initial_state"],
        "states": list(config["states"].keys()),
        "message": f"Workflow '{config.get('name')}' initialized. Call wf_status() to begin.",
    }


# ── Entry point ──────────────────────────────────────────────────

def main():
    """Run the MCP server via stdio transport."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
