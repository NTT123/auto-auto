"""
Claude Code hook scripts for the auto-auto workflow engine.

These run as separate processes when Claude Code fires hook events:
- Stop: intercepts the model attempting to stop. Blocks if workflow has
  unfinished work (pending tasks, pending gates, active infinite loop).
- SessionStart: injects the current workflow context into the model's first
  prompt, so the model wakes up grounded without needing to call wf_status().

Invoked via:
    python -m workflow_engine.hooks Stop
    python -m workflow_engine.hooks SessionStart

These hooks are the "background pressure" layer of auto-auto: they engage
the workflow without requiring the model to remember to call any tool.

Failsafe philosophy: if anything in the hook errors, allow the user to
proceed. Never trap them in a broken hook.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from workflow_engine.engine import TaskStatus, WorkflowEngine


# ── Helpers ──────────────────────────────────────────────────────


def _resolve_workflow_dir(payload: dict[str, Any]) -> Path:
    """Figure out where the .workflow/ directory lives.

    Resolution order:
      1. WORKFLOW_DIR env var if set (matches the MCP server's resolution)
      2. <cwd from stdin payload>/.workflow
      3. ./.workflow
    """
    if "WORKFLOW_DIR" in os.environ:
        return Path(os.environ["WORKFLOW_DIR"])
    if payload.get("cwd"):
        return Path(payload["cwd"]) / ".workflow"
    return Path(".workflow")


def _load_engine(workflow_dir: Path) -> WorkflowEngine | None:
    """Try to load the workflow engine. Return None if no workflow loaded."""
    if not workflow_dir.exists():
        return None
    try:
        engine = WorkflowEngine(workflow_dir)
    except Exception:
        return None
    if not engine.is_loaded:
        return None
    return engine


def _build_context_payload(engine: WorkflowEngine) -> str:
    """Build a rich context string describing the current workflow state.

    Used by both the SessionStart hook (to ground the model on session start)
    and the Stop hook (to refresh context when blocking a premature exit).
    """
    state_def = engine.get_state_def()
    pending_tasks = [
        t for t in engine.tasks.values() if t.status != TaskStatus.DONE
    ]

    lines: list[str] = []
    lines.append("=== AUTO-AUTO WORKFLOW CONTEXT ===")
    lines.append(f"Workflow: {engine.config.get('name', 'unnamed')}")
    if engine.config.get("goal"):
        lines.append(f"Goal: {engine.config['goal']}")
    if engine.config.get("pattern"):
        lines.append(f"Pattern: {engine.config['pattern']}")
    lines.append("")
    lines.append(f"Current state: {engine.current_state}")
    if state_def.get("instruction"):
        lines.append("Instruction for this state:")
        for instr_line in state_def["instruction"].splitlines():
            lines.append(f"  {instr_line}")
    lines.append("")

    # Tasks
    if pending_tasks:
        lines.append(f"Pending tasks ({len(pending_tasks)}):")
        for t in pending_tasks[:10]:
            marker = "▶" if t.status == TaskStatus.IN_PROGRESS else "○"
            lines.append(f"  {marker} [{t.id}] {t.name} ({t.status.value})")
        if len(pending_tasks) > 10:
            lines.append(f"  … and {len(pending_tasks) - 10} more")
        lines.append("")
    else:
        done_count = sum(
            1 for t in engine.tasks.values() if t.status == TaskStatus.DONE
        )
        if done_count:
            lines.append(f"Tasks: {done_count} done, 0 pending")
            lines.append("")

    # Recent reflections — these carry the model's memory of decisions made
    if engine.reflections:
        recent = engine.reflections[-5:]
        lines.append(
            f"Recent reflections (showing {len(recent)} of {len(engine.reflections)}):"
        )
        for r in recent:
            content = r.content.replace("\n", " ").strip()
            if len(content) > 200:
                content = content[:197] + "…"
            lines.append(f"  • [{r.state}] {content}")
        lines.append("")

    # Recent verification gates — what's been verified, what hasn't
    if engine.gates:
        recent_gates = engine.gates[-5:]
        lines.append(
            f"Recent verification gates (showing {len(recent_gates)} of {len(engine.gates)}):"
        )
        for g in recent_gates:
            mark = "✓" if g.passed else "✗"
            evidence = g.evidence.replace("\n", " ").strip()
            if len(evidence) > 100:
                evidence = evidence[:97] + "…"
            lines.append(f"  {mark} {g.criteria} — {evidence}")
        lines.append("")

    # Loop state — critical for catching circles and infinite-mode escapes
    if engine.iterations:
        loop_status = engine.get_loop_status()
        mode = loop_status.get("mode", "bounded")
        active = loop_status.get("active", False)
        marker = "♾️ " if mode == "infinite" else ""
        lines.append(
            f"{marker}Loop: iteration {loop_status.get('current_iteration', 0)} / "
            f"{loop_status.get('total_iterations', 0)} total ({mode}, "
            f"{'active' if active else 'closed'})"
        )
        if loop_status.get("current_focus"):
            lines.append(f"  Current focus: {loop_status['current_focus']}")
        if loop_status.get("converging") is False:
            lines.append(
                "  ⚠️  Convergence warning: remaining_issues count is not decreasing."
            )
        lines.append("")

    # Available transitions and their readiness
    transitions = engine.get_available_transitions()
    if transitions:
        lines.append("Available transitions from this state:")
        for t_name in transitions:
            allowed, blockers = engine.check_transition_requirements(t_name)
            if allowed:
                lines.append(f"  → {t_name} (ready)")
            else:
                blocker_str = "; ".join(blockers)
                if len(blocker_str) > 150:
                    blocker_str = blocker_str[:147] + "…"
                lines.append(f"  → {t_name} (blocked: {blocker_str})")
        lines.append("")

    lines.append("=== END WORKFLOW CONTEXT ===")
    lines.append("")
    lines.append(
        "Tip: call wf_resume() for a compact 'where was I' summary, "
        "wf_status() for the brief live dashboard, or wf_status(mode='full') "
        "for the full firehose."
    )

    return "\n".join(lines)


def _state_requires(engine: WorkflowEngine, state_name: str, requirement: str) -> bool:
    """True if the named state has at least one outgoing transition that lists
    `requirement` in its `requires` array.

    Used to dynamically classify states as "work" (requires all_tasks_done) or
    "verify" (requires gate_passed) based on the workflow config — so custom
    workflow templates with non-standard state names still get the right
    treatment from the Stop hook.
    """
    state_def = engine.get_state_def(state_name)
    for t_def in state_def.get("transitions", {}).values():
        if requirement in t_def.get("requires", []):
            return True
    return False


def _diagnose_unfinished_work(engine: WorkflowEngine) -> list[str]:
    """Identify reasons the model should NOT be allowed to stop.

    Returns a list of human-readable block reasons. Empty list means
    stopping is fine — no unfinished work.
    """
    reasons: list[str] = []

    # Terminal state — always allow stop
    if engine.current_state == "done":
        return []

    # 1. Active infinite loop that hasn't been force-stopped
    if (
        engine.loop_active
        and engine.loop_mode == "infinite"
        and not engine.loop_force_stopped
    ):
        current = engine.iterations[-1] if engine.iterations else None
        focus = current.focus if current and current.focus else "(no focus set)"
        reasons.append(
            f"♾️  An INFINITE LOOP is active (iteration "
            f"{len(engine.iterations)}, focus: {focus}). Infinite loops cannot "
            f"stop with verdict='done'. Either continue with "
            f"wf_loop(action='next', focus='...') or explicitly terminate with "
            f"wf_loop(action='force_stop', reason='...')."
        )

    # 2. Tasks marked in_progress anywhere — you started something, finish it.
    # This check is state-agnostic: if you're working on something, finish it.
    in_progress = [
        t for t in engine.tasks.values() if t.status == TaskStatus.IN_PROGRESS
    ]
    if in_progress:
        task_list = "\n".join(
            f"    - [{t.id}] {t.name}" for t in in_progress[:5]
        )
        more = (
            f"\n    … and {len(in_progress) - 5} more"
            if len(in_progress) > 5
            else ""
        )
        reasons.append(
            f"{len(in_progress)} task(s) are still IN-PROGRESS:\n{task_list}{more}\n"
            f"  Finish them and call wf_task(action='done', task_id='...') for each."
        )

    # 3. Pending verification checks while in a verify-like state.
    # A "verify state" is dynamically defined as any state with an outgoing
    # transition that requires gate_passed. This works for any workflow
    # template, not just ones that name their state literally "verify".
    if _state_requires(engine, engine.current_state, "gate_passed"):
        pending_checks = engine.get_pending_checks()
        if pending_checks:
            check_list = "\n".join(
                f"    - {c.get('criteria', '(unnamed)')}"
                for c in pending_checks[:5]
            )
            more = (
                f"\n    … and {len(pending_checks) - 5} more"
                if len(pending_checks) > 5
                else ""
            )
            reasons.append(
                f"You are in '{engine.current_state}' with "
                f"{len(pending_checks)} pending verification check(s):\n"
                f"{check_list}{more}\n"
                f"  Call wf_verify() to see the plan, run each check, and record "
                f"the result with wf_gate(criteria='...', passed=..., evidence='...')."
            )

    # 4. Pending tasks while in a work-like state.
    # A "work state" is dynamically defined as any state with an outgoing
    # transition that requires all_tasks_done. Custom workflow templates with
    # state names like "build", "code", "implement" all get caught by this.
    if _state_requires(engine, engine.current_state, "all_tasks_done"):
        pending = [
            t for t in engine.tasks.values() if t.status == TaskStatus.PENDING
        ]
        if pending:
            task_list = "\n".join(
                f"    - [{t.id}] {t.name}" for t in pending[:5]
            )
            more = (
                f"\n    … and {len(pending) - 5} more"
                if len(pending) > 5
                else ""
            )
            reasons.append(
                f"You are in '{engine.current_state}' but {len(pending)} task(s) "
                f"are still PENDING:\n{task_list}{more}\n"
                f"  Pick the next one with "
                f"wf_task(action='update', task_id='...', status='in_progress')."
            )

    return reasons


# ── Hook entry points ────────────────────────────────────────────


def stop_hook(payload: dict[str, Any]) -> tuple[int, str]:
    """Stop hook: intercept model attempting to stop.

    Returns (exit_code, stdout_text).

    - exit 0 with empty stdout: allow the stop
    - exit 0 with JSON {"decision": "block", "reason": "..."}: block and
      force the model to continue with the given reason
    """
    workflow_dir = _resolve_workflow_dir(payload)
    engine = _load_engine(workflow_dir)

    # No workflow loaded → not an auto-auto workspace, allow stop
    if engine is None:
        return 0, ""

    block_reasons = _diagnose_unfinished_work(engine)
    if not block_reasons:
        # All clear — let the model stop
        return 0, ""

    # Block the stop with a rich message: tell the model what's pending
    # AND give it a context refresh so it doesn't need to call wf_status.
    context = _build_context_payload(engine)
    reason_text = (
        "🛑 STOP BLOCKED by auto-auto workflow.\n\n"
        "You are trying to end your turn, but the workflow has unfinished work:\n\n"
        + "\n\n".join(block_reasons)
        + "\n\n"
        + context
    )

    response = {
        "decision": "block",
        "reason": reason_text,
    }
    return 0, json.dumps(response)


def session_start_hook(payload: dict[str, Any]) -> tuple[int, str]:
    """SessionStart hook: inject workflow context into the model's first prompt.

    Returns (exit_code, stdout_text).

    Outputs a JSON payload with hookSpecificOutput.additionalContext, which
    Claude Code splices into the model's first user prompt. This way the
    model wakes up already grounded — it knows what workflow it's in, what
    state, what tasks remain, what was decided previously.

    Triggers via matchers in settings.json: startup, resume, compact.
    """
    workflow_dir = _resolve_workflow_dir(payload)
    engine = _load_engine(workflow_dir)

    if engine is None:
        # Not an auto-auto workspace — nothing to inject
        return 0, ""

    context = _build_context_payload(engine)

    response = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": context,
        }
    }
    return 0, json.dumps(response)


# ── CLI dispatcher ───────────────────────────────────────────────


def main() -> None:
    """CLI dispatcher: python -m workflow_engine.hooks <Stop|SessionStart>.

    Reads JSON payload from stdin, dispatches to the appropriate hook,
    writes the response (if any) to stdout, exits with the hook's exit code.

    Failsafe: any unexpected exception is caught and the stop is allowed,
    so a broken hook never traps the user.
    """
    try:
        if len(sys.argv) < 2:
            print(
                "Usage: python -m workflow_engine.hooks <Stop|SessionStart>",
                file=sys.stderr,
            )
            sys.exit(0)

        name = sys.argv[1]

        # Read stdin payload (Claude Code sends JSON with cwd, session_id, etc.)
        try:
            stdin_text = sys.stdin.read()
            payload = json.loads(stdin_text) if stdin_text.strip() else {}
        except (json.JSONDecodeError, ValueError):
            payload = {}

        if name == "Stop":
            code, output = stop_hook(payload)
        elif name == "SessionStart":
            code, output = session_start_hook(payload)
        else:
            print(
                f"Unknown hook: {name}. Use Stop or SessionStart.",
                file=sys.stderr,
            )
            sys.exit(0)

        if output:
            sys.stdout.write(output)
            sys.stdout.flush()
        sys.exit(code)

    except Exception as e:
        # Failsafe — never trap the user in a broken hook
        print(f"auto-auto hook error: {e}", file=sys.stderr)
        sys.exit(0)


if __name__ == "__main__":
    main()
