"""
Workflow state machine engine.

Manages workflow definitions, state transitions, tasks, gates, and reflections.
All state is persisted to .workflow/ directory on disk.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any


class TaskStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    BLOCKED = "blocked"


@dataclass
class Task:
    id: str
    name: str
    description: str = ""
    status: TaskStatus = TaskStatus.PENDING
    state: str = ""  # which workflow state this task belongs to
    parent_id: str | None = None  # for subtasks
    created_at: float = field(default_factory=time.time)
    completed_at: float | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> Task:
        d = d.copy()
        d["status"] = TaskStatus(d["status"])
        return cls(**d)


@dataclass
class GateResult:
    criteria: str
    passed: bool
    evidence: str
    timestamp: float = field(default_factory=time.time)
    iteration: int = 0  # Which loop iteration this gate belongs to (0 = pre-loop / v1)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> GateResult:
        # Backward-compat: older state.json files may lack `iteration`
        d = d.copy()
        d.setdefault("iteration", 0)
        return cls(**d)


@dataclass
class Reflection:
    content: str
    state: str
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> Reflection:
        return cls(**d)


@dataclass
class TransitionRecord:
    from_state: str
    to_state: str
    reason: str
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> TransitionRecord:
        return cls(**d)


@dataclass
class IterationRecord:
    """Tracks one pass through a loop."""
    iteration: int
    started_at: float = field(default_factory=time.time)
    completed_at: float | None = None
    focus: str = ""          # what this iteration aims to improve
    outcome: str = ""        # what actually happened
    improvements: list[str] = field(default_factory=list)  # concrete things that got better
    remaining_issues: list[str] = field(default_factory=list)  # things still to fix
    verdict: str = ""        # "continue" | "done" | "" (not decided yet)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "IterationRecord":
        return cls(**d)


class WorkflowEngine:
    """Core state machine engine for workflow management."""

    def __init__(self, workflow_dir: Path):
        self.workflow_dir = Path(workflow_dir)
        self.config_path = self.workflow_dir / "config.json"
        self.state_path = self.workflow_dir / "state.json"

        self.config: dict = {}
        self.current_state: str = ""
        self.tasks: dict[str, Task] = {}
        self.gates: list[GateResult] = []
        self.reflections: list[Reflection] = []
        self.history: list[TransitionRecord] = []
        self._task_counter: int = 0

        # Loop tracking
        self.loop_active: bool = False
        self.loop_mode: str = "bounded"   # "bounded" | "infinite"
        self.loop_entry_state: str = ""   # the state where the loop begins
        self.loop_max_iterations: int = 0  # 0 = no limit (only meaningful for bounded)
        self.loop_force_stopped: bool = False  # explicit user/model termination
        self.iterations: list[IterationRecord] = []

        self._load()

    # ── Persistence ──────────────────────────────────────────────

    def _load(self):
        """Load workflow config and state from disk."""
        if self.config_path.exists():
            self.config = json.loads(self.config_path.read_text())
            self.current_state = self.config.get("initial_state", "")

        if self.state_path.exists():
            state = json.loads(self.state_path.read_text())
            self.current_state = state.get("current_state", self.current_state)
            self.tasks = {
                k: Task.from_dict(v) for k, v in state.get("tasks", {}).items()
            }
            self.gates = [GateResult.from_dict(g) for g in state.get("gates", [])]
            self.reflections = [
                Reflection.from_dict(r) for r in state.get("reflections", [])
            ]
            self.history = [
                TransitionRecord.from_dict(h) for h in state.get("history", [])
            ]
            self._task_counter = state.get("task_counter", 0)
            # Loop state
            self.loop_active = state.get("loop_active", False)
            self.loop_mode = state.get("loop_mode", "bounded")
            self.loop_entry_state = state.get("loop_entry_state", "")
            self.loop_max_iterations = state.get("loop_max_iterations", 0)
            self.loop_force_stopped = state.get("loop_force_stopped", False)
            self.iterations = [
                IterationRecord.from_dict(i) for i in state.get("iterations", [])
            ]

    def _save(self):
        """Persist current state to disk."""
        self.workflow_dir.mkdir(parents=True, exist_ok=True)
        state = {
            "current_state": self.current_state,
            "tasks": {k: v.to_dict() for k, v in self.tasks.items()},
            "gates": [g.to_dict() for g in self.gates],
            "reflections": [r.to_dict() for r in self.reflections],
            "history": [h.to_dict() for h in self.history],
            "task_counter": self._task_counter,
            "loop_active": self.loop_active,
            "loop_mode": self.loop_mode,
            "loop_entry_state": self.loop_entry_state,
            "loop_max_iterations": self.loop_max_iterations,
            "loop_force_stopped": self.loop_force_stopped,
            "iterations": [i.to_dict() for i in self.iterations],
        }
        self.state_path.write_text(json.dumps(state, indent=2))

    def reload_config(self):
        """Reload workflow config from disk (called when skill updates it)."""
        if self.config_path.exists():
            self.config = json.loads(self.config_path.read_text())
            # If no state yet, initialize
            if not self.current_state and self.config.get("initial_state"):
                self.current_state = self.config["initial_state"]
                self._save()

    @property
    def is_loaded(self) -> bool:
        return bool(self.config) and bool(self.current_state)

    # ── State Machine ────────────────────────────────────────────

    def get_state_def(self, state_name: str | None = None) -> dict:
        """Get the definition for a state from the workflow config."""
        name = state_name or self.current_state
        states = self.config.get("states", {})
        return states.get(name, {})

    def get_available_transitions(self) -> dict[str, dict]:
        """Get transitions available from the current state."""
        state_def = self.get_state_def()
        return state_def.get("transitions", {})

    def check_transition_requirements(self, target_state: str) -> tuple[bool, list[str]]:
        """Check if a transition is allowed. Returns (allowed, reasons)."""
        transitions = self.get_available_transitions()
        if target_state not in transitions:
            return False, [
                f"No transition from '{self.current_state}' to '{target_state}'. "
                f"Available: {list(transitions.keys())}"
            ]

        transition_def = transitions[target_state]
        requires = transition_def.get("requires", [])
        failures = []

        for req in requires:
            if req == "all_tasks_done":
                # Check ALL tasks in the workflow, not just current state.
                # Tasks from planning carry into execution.
                all_tasks = list(self.tasks.values())
                pending = [t for t in all_tasks if t.status != TaskStatus.DONE]
                if pending:
                    names = [t.name for t in pending]
                    failures.append(
                        f"Tasks not done: {names}"
                    )
                if not all_tasks:
                    failures.append(
                        "No tasks exist in the workflow. Create tasks first."
                    )

            elif req == "all_tasks_defined":
                state_tasks = self._get_state_tasks(self.current_state)
                if not state_tasks:
                    failures.append(
                        f"No tasks defined in '{self.current_state}'. "
                        "Create at least one task before transitioning."
                    )

            elif req == "gate_passed":
                state_gates = [
                    g for g in self.gates
                    if g.passed
                    # Only count gates from the current state visit
                    and (not self.history or g.timestamp > self.history[-1].timestamp)
                ]
                if not state_gates:
                    failures.append(
                        f"No passing gate check in '{self.current_state}'. "
                        "Run wf_gate() with passing criteria first."
                    )

            elif req == "has_reflection":
                state_reflections = [
                    r for r in self.reflections
                    if r.state == self.current_state
                    and (not self.history or r.timestamp > self.history[-1].timestamp)
                ]
                if not state_reflections:
                    failures.append(
                        f"No reflection logged in '{self.current_state}'. "
                        "Use wf_reflect() first."
                    )

        return len(failures) == 0, failures

    def transition(self, target_state: str, reason: str = "") -> dict:
        """Execute a state transition. Returns result dict."""
        allowed, failures = self.check_transition_requirements(target_state)
        if not allowed:
            return {
                "success": False,
                "error": "Transition blocked",
                "reasons": failures,
                "current_state": self.current_state,
            }

        old_state = self.current_state
        record = TransitionRecord(
            from_state=old_state,
            to_state=target_state,
            reason=reason,
        )
        self.history.append(record)
        self.current_state = target_state
        self._save()

        new_state_def = self.get_state_def()
        return {
            "success": True,
            "from": old_state,
            "to": target_state,
            "instruction": new_state_def.get("instruction", ""),
            "available_transitions": list(
                new_state_def.get("transitions", {}).keys()
            ),
        }

    # ── Tasks ────────────────────────────────────────────────────

    def _get_state_tasks(self, state_name: str) -> list[Task]:
        """Get all tasks for a given state."""
        return [t for t in self.tasks.values() if t.state == state_name]

    def create_task(
        self,
        name: str,
        description: str = "",
        state: str | None = None,
        parent_id: str | None = None,
    ) -> Task:
        """Create a new task in the current (or specified) state."""
        self._task_counter += 1
        task_id = f"t{self._task_counter}"
        task = Task(
            id=task_id,
            name=name,
            description=description,
            status=TaskStatus.PENDING,
            state=state or self.current_state,
            parent_id=parent_id,
        )
        self.tasks[task_id] = task
        self._save()
        return task

    def update_task(self, task_id: str, status: str | None = None, name: str | None = None, description: str | None = None) -> Task:
        """Update a task's status, name, or description."""
        if task_id not in self.tasks:
            raise ValueError(f"Task '{task_id}' not found")

        task = self.tasks[task_id]
        if status:
            task.status = TaskStatus(status)
            if task.status == TaskStatus.DONE:
                task.completed_at = time.time()
        if name:
            task.name = name
        if description:
            task.description = description
        self._save()
        return task

    def list_tasks(self, state: str | None = None, status: str | None = None) -> list[Task]:
        """List tasks, optionally filtered by state and/or status."""
        tasks = list(self.tasks.values())
        if state:
            tasks = [t for t in tasks if t.state == state]
        if status:
            tasks = [t for t in tasks if t.status.value == status]
        return tasks

    # ── Verification ────────────────────────────────────────────

    def get_verification_plan(self) -> dict:
        """Get the verification plan from the workflow config.

        The verification section defines HOW to verify, ranked by preference:
        1. automated_tests — write/run test cases (best: fast, repeatable)
        2. output_inspection — read and check output files (text, image, pdf)
        3. browser_check — use Chrome DevTools to inspect rendered pages
        4. agent_review — spawn a reviewer Claude Code instance
        5. user_review — ask the user (last resort, bottleneck)
        """
        return self.config.get("verification", {})

    def get_pending_checks(self) -> list[dict]:
        """Get verification checks that haven't passed yet."""
        plan = self.get_verification_plan()
        checks = plan.get("checks", [])

        # Find which checks have passing gates
        passed_criteria = {g.criteria for g in self.gates if g.passed}

        pending = []
        for check in checks:
            if check.get("criteria") not in passed_criteria:
                pending.append(check)
        return pending

    def check_gate(
        self,
        criteria: str,
        passed: bool,
        evidence: str,
        iteration: int | None = None,
    ) -> GateResult:
        """Record a verification gate check.

        If `iteration` is None, it is inferred from the active loop:
        - an active loop uses its current_iteration
        - no loop (or no iterations yet) defaults to 0 (pre-loop / v1)
        """
        if iteration is None:
            iteration = self.iterations[-1].iteration if self.iterations else 0
        gate = GateResult(
            criteria=criteria,
            passed=passed,
            evidence=evidence,
            iteration=iteration,
        )
        self.gates.append(gate)
        self._save()
        return gate

    def get_gate_history_by_criteria(self, criteria: str) -> list[GateResult]:
        """All gate records for a given criteria, oldest→newest.

        Useful for spotting regressions across iterations: the same criteria
        may have different results in different iterations.
        """
        return [g for g in self.gates if g.criteria == criteria]

    # ── Loop Management ────────────────────────────────────────

    def start_loop(
        self,
        focus: str,
        mode: str = "bounded",
        max_iterations: int = 0,
    ) -> IterationRecord:
        """Begin a new improvement loop from the current state.

        Args:
            focus: What this iteration aims to improve
            mode: "bounded" (model can stop with verdict='done') or
                  "infinite" (model is pushed to keep going indefinitely)
            max_iterations: Optional safety cap (0 = no limit). Even infinite
                  loops can have a max as a safety net.
        """
        if mode not in ("bounded", "infinite"):
            raise ValueError(f"Invalid mode '{mode}'. Use 'bounded' or 'infinite'.")

        self.loop_active = True
        self.loop_mode = mode
        self.loop_entry_state = self.current_state
        self.loop_max_iterations = max_iterations
        self.loop_force_stopped = False

        iteration = IterationRecord(
            iteration=len(self.iterations) + 1,
            focus=focus,
        )
        self.iterations.append(iteration)
        self._save()
        return iteration

    def next_iteration(self, focus: str) -> IterationRecord:
        """Start the next iteration of an active loop.

        Call this when re-entering the loop entry state.
        """
        if not self.loop_active:
            return self.start_loop(focus)

        # Close the previous iteration if it's still open
        if self.iterations and not self.iterations[-1].completed_at:
            self.iterations[-1].completed_at = time.time()

        iteration = IterationRecord(
            iteration=len(self.iterations) + 1,
            focus=focus,
        )
        self.iterations.append(iteration)
        self._save()
        return iteration

    def update_iteration(
        self,
        outcome: str = "",
        improvements: list[str] | None = None,
        remaining_issues: list[str] | None = None,
        verdict: str = "",
    ) -> tuple[IterationRecord | None, bool]:
        """Update the current iteration with results.

        Returns (iteration, accepted_done) — `accepted_done` is True if a
        verdict='done' actually closed the loop. In infinite mode, verdict='done'
        is silently rewritten to 'continue' (loop stays active).
        """
        if not self.iterations:
            return None, False

        current = self.iterations[-1]
        if outcome:
            current.outcome = outcome
        if improvements is not None:
            current.improvements = improvements
        if remaining_issues is not None:
            current.remaining_issues = remaining_issues

        accepted_done = False
        if verdict:
            if verdict == "done":
                if self.loop_mode == "infinite" and not self.loop_force_stopped:
                    # Infinite loop: don't accept "done", coerce to "continue"
                    current.verdict = "continue"
                    current.completed_at = time.time()
                    accepted_done = False
                else:
                    current.verdict = "done"
                    current.completed_at = time.time()
                    self.loop_active = False
                    accepted_done = True
            elif verdict == "continue":
                current.verdict = "continue"
                current.completed_at = time.time()
        self._save()
        return current, accepted_done

    def force_stop_loop(self, reason: str = "") -> dict:
        """Forcibly stop a loop, including infinite ones.

        This is the only way to exit an infinite loop. Use sparingly —
        the whole point of an infinite loop is to keep the model from
        giving up too early.
        """
        if not self.loop_active and not self.iterations:
            return {"stopped": False, "error": "No active loop to stop."}

        was_infinite = self.loop_mode == "infinite"
        self.loop_active = False
        self.loop_force_stopped = True

        # Close current iteration if open
        if self.iterations and not self.iterations[-1].completed_at:
            self.iterations[-1].completed_at = time.time()
            self.iterations[-1].verdict = "force_stopped"
            if reason:
                self.iterations[-1].outcome = (
                    self.iterations[-1].outcome + f" [FORCE STOP: {reason}]"
                ).strip()

        self._save()
        return {
            "stopped": True,
            "was_infinite": was_infinite,
            "total_iterations": len(self.iterations),
            "reason": reason,
        }

    def get_loop_status(self) -> dict:
        """Get comprehensive loop status including convergence analysis."""
        if not self.iterations:
            return {
                "active": False,
                "iterations": 0,
                "message": "No loop started. Use wf_loop(action='start', ...) to begin iterating.",
            }

        current = self.iterations[-1]
        completed = [i for i in self.iterations if i.completed_at]

        # Convergence analysis: are remaining issues decreasing?
        issue_trend = []
        for it in self.iterations:
            if it.remaining_issues is not None:
                issue_trend.append(len(it.remaining_issues))

        converging = None
        if len(issue_trend) >= 2:
            converging = issue_trend[-1] <= issue_trend[-2]

        # Build iteration summaries
        summaries = []
        for it in self.iterations:
            summaries.append({
                "iteration": it.iteration,
                "focus": it.focus,
                "outcome": it.outcome,
                "improvements": it.improvements,
                "remaining_issues": it.remaining_issues,
                "verdict": it.verdict,
            })

        # Safety cap status
        cap_reached = False
        if self.loop_max_iterations > 0 and len(self.iterations) >= self.loop_max_iterations:
            cap_reached = True

        return {
            "active": self.loop_active,
            "mode": self.loop_mode,
            "force_stopped": self.loop_force_stopped,
            "entry_state": self.loop_entry_state,
            "current_iteration": current.iteration,
            "total_iterations": len(self.iterations),
            "max_iterations": self.loop_max_iterations,
            "max_iterations_reached": cap_reached,
            "completed_iterations": len(completed),
            "current_focus": current.focus,
            "converging": converging,
            "issue_trend": issue_trend,
            "iterations": summaries,
        }

    # ── Next-action hint ─────────────────────────────────────────

    def _state_requires(self, requirement: str, state_name: str | None = None) -> bool:
        """True if the named state (default: current) has an outgoing transition
        that declares `requirement` in its `requires` array.

        Used to classify states as work-like (all_tasks_done) or verify-like
        (gate_passed) without hardcoding state names — works for any template.
        """
        state_def = self.get_state_def(state_name)
        for t_def in state_def.get("transitions", {}).values():
            if requirement in t_def.get("requires", []):
                return True
        return False

    def compute_next_action(self) -> dict | None:
        """Heuristically suggest the single most useful next action.

        Returns a dict with at least a `suggestion` string, plus optional
        `kind`, `tool`, `command`, `then` fields — or None if nothing
        sensible can be suggested (e.g., workflow not loaded, terminal state).

        The server layer injects this into every wf_* response so the model
        doesn't have to synthesize "what now?" from three different sources.
        """
        if not self.is_loaded:
            return None

        # Terminal state: nothing to do
        if self.current_state == "done":
            return {
                "kind": "done",
                "suggestion": "Workflow is in the terminal 'done' state. Nothing more to do.",
            }

        # 1. In-progress tasks take priority — if you started something, finish it
        in_progress = [
            t for t in self.tasks.values() if t.status == TaskStatus.IN_PROGRESS
        ]
        if in_progress:
            t = in_progress[0]
            return {
                "kind": "finish_task",
                "suggestion": (
                    f"Finish in-progress task [{t.id}] '{t.name}', then mark it done "
                    f"with wf_task(action='done', task_id='{t.id}')."
                ),
                "task_id": t.id,
                "then": f"wf_task(action='done', task_id='{t.id}')",
            }

        # 2. Verify-like state with pending checks → run the first pending check
        if self._state_requires("gate_passed"):
            pending = self.get_pending_checks()
            if pending:
                first = pending[0]
                criteria = first.get("criteria", "(unnamed)")
                method = first.get("method", "")
                command = first.get("command", "")
                how = first.get("how", "")

                parts = [f"Run pending check: '{criteria}'"]
                if method:
                    parts.append(f"(method: {method})")
                if command:
                    parts.append(f"via `{command}`")
                elif how:
                    parts.append(f"— {how}")
                parts.append(
                    f"then record the result with "
                    f"wf_gate(criteria='{criteria}', passed=..., evidence='...')."
                )

                return {
                    "kind": "run_check",
                    "suggestion": " ".join(parts),
                    "criteria": criteria,
                    "method": method,
                    "command": command,
                    "then": (
                        f"wf_gate(criteria={criteria!r}, passed=True|False, "
                        f"evidence='...')"
                    ),
                }
            # All checks passed in a verify-like state → transition
            transitions = self.get_available_transitions()
            ready = [
                name for name in transitions
                if self.check_transition_requirements(name)[0]
            ]
            if ready:
                target = ready[0]
                return {
                    "kind": "transition",
                    "suggestion": (
                        f"All verification checks have passed. Transition to "
                        f"'{target}' with wf_transition(to_state='{target}', "
                        f"reason='verification complete')."
                    ),
                    "target": target,
                    "then": f"wf_transition(to_state={target!r})",
                }

        # 3. Work-like state with pending tasks → pick one up
        if self._state_requires("all_tasks_done"):
            pending_tasks = [
                t for t in self.tasks.values() if t.status == TaskStatus.PENDING
            ]
            if pending_tasks:
                t = pending_tasks[0]
                return {
                    "kind": "start_task",
                    "suggestion": (
                        f"Pick up task [{t.id}] '{t.name}'. Mark it in-progress "
                        f"with wf_task(action='update', task_id='{t.id}', "
                        f"status='in_progress'), do the work, then mark done."
                    ),
                    "task_id": t.id,
                    "then": (
                        f"wf_task(action='update', task_id={t.id!r}, "
                        f"status='in_progress')"
                    ),
                }
            # All tasks done → transition out
            transitions = self.get_available_transitions()
            ready = [
                name for name in transitions
                if self.check_transition_requirements(name)[0]
            ]
            if ready:
                target = ready[0]
                return {
                    "kind": "transition",
                    "suggestion": (
                        f"All tasks done. Transition to '{target}' with "
                        f"wf_transition(to_state='{target}', reason='work complete')."
                    ),
                    "target": target,
                    "then": f"wf_transition(to_state={target!r})",
                }

        # 4. Planning-like state: needs tasks defined before moving on
        if self._state_requires("all_tasks_defined"):
            state_tasks = self._get_state_tasks(self.current_state)
            if not state_tasks:
                return {
                    "kind": "define_tasks",
                    "suggestion": (
                        "No tasks defined yet. Break the goal into concrete tasks "
                        "with wf_task(action='create', name='...', description='...')."
                    ),
                    "then": "wf_task(action='create', name='...')",
                }
            transitions = self.get_available_transitions()
            ready = [
                name for name in transitions
                if self.check_transition_requirements(name)[0]
            ]
            if ready:
                target = ready[0]
                return {
                    "kind": "transition",
                    "suggestion": (
                        f"Tasks are defined. Transition to '{target}' with "
                        f"wf_transition(to_state='{target}', reason='plan ready')."
                    ),
                    "target": target,
                    "then": f"wf_transition(to_state={target!r})",
                }

        # 5. Reflect-like state: needs a reflection before moving on
        if self._state_requires("has_reflection"):
            state_reflections = [
                r for r in self.reflections
                if r.state == self.current_state
                and (not self.history or r.timestamp > self.history[-1].timestamp)
            ]
            if not state_reflections:
                return {
                    "kind": "reflect",
                    "suggestion": (
                        "Log a reflection for this state with wf_reflect(content='...'). "
                        "Capture what you learned and what to do differently."
                    ),
                    "then": "wf_reflect(content='...')",
                }

        # 6. Fallback: is any transition ready?
        transitions = self.get_available_transitions()
        ready = [
            name for name in transitions
            if self.check_transition_requirements(name)[0]
        ]
        if ready:
            target = ready[0]
            return {
                "kind": "transition",
                "suggestion": (
                    f"You can transition to '{target}' with "
                    f"wf_transition(to_state='{target}')."
                ),
                "target": target,
                "then": f"wf_transition(to_state={target!r})",
            }

        # 7. Nothing obvious — point at wf_state
        return {
            "kind": "unknown",
            "suggestion": (
                f"Inspect state '{self.current_state}' with wf_state() to see what "
                f"is required. Check wf_next() for available transitions and blockers."
            ),
            "then": "wf_state()",
        }

    # ── Reflections ──────────────────────────────────────────────

    def add_reflection(self, content: str) -> Reflection:
        """Log a reflection for the current state."""
        reflection = Reflection(content=content, state=self.current_state)
        self.reflections.append(reflection)
        self._save()
        return reflection

    # ── Status / Dashboard ───────────────────────────────────────

    def get_full_status(self) -> dict:
        """Get complete workflow status — the full dashboard."""
        if not self.is_loaded:
            return {
                "loaded": False,
                "message": "No workflow loaded. Run /auto-auto from the auto-auto "
                "project to design one, or place a config.json in .workflow/",
            }

        state_def = self.get_state_def()
        transitions = self.get_available_transitions()
        state_tasks = self._get_state_tasks(self.current_state)

        # Check which transitions are currently possible
        transition_status = {}
        for t_name in transitions:
            allowed, reasons = self.check_transition_requirements(t_name)
            transition_status[t_name] = {
                "allowed": allowed,
                "blockers": reasons if not allowed else [],
            }

        # Recent reflections (last 3)
        recent_reflections = [
            r.to_dict() for r in self.reflections[-3:]
        ]

        # Task summary
        all_tasks = list(self.tasks.values())
        task_summary = {
            "total": len(all_tasks),
            "pending": len([t for t in all_tasks if t.status == TaskStatus.PENDING]),
            "in_progress": len([t for t in all_tasks if t.status == TaskStatus.IN_PROGRESS]),
            "done": len([t for t in all_tasks if t.status == TaskStatus.DONE]),
        }

        # Verification plan summary
        v_plan = self.get_verification_plan()
        v_pending = self.get_pending_checks()
        verification_summary = None
        if v_plan:
            verification_summary = {
                "strategy": v_plan.get("strategy", "unknown"),
                "total_checks": len(v_plan.get("checks", [])),
                "pending_checks": len(v_pending),
                "passed_checks": len(v_plan.get("checks", [])) - len(v_pending),
            }

        return {
            "loaded": True,
            "mode": "full",
            "workflow": {
                "name": self.config.get("name", "unnamed"),
                "goal": self.config.get("goal", ""),
                "pattern": self.config.get("pattern", ""),
            },
            "current_state": self.current_state,
            "instruction": state_def.get("instruction", ""),
            "tasks_in_state": [t.to_dict() for t in state_tasks],
            "task_summary": task_summary,
            "transitions": transition_status,
            "recent_reflections": recent_reflections,
            "transition_count": len(self.history),
            "total_reflections": len(self.reflections),
            "total_gates": len(self.gates),
            "gates_passed": len([g for g in self.gates if g.passed]),
            "verification": verification_summary,
            "loop": self.get_loop_status() if self.iterations else None,
        }

    def _loop_summary(self) -> dict | None:
        """Compact loop status — just the signals, not the history.

        Used by brief status and resume. Contains only the fields the model
        actually consumes to decide "where am I in the loop?": active,
        current iteration, total, converging flag, mode, focus. Excludes the
        full iterations array and per-iteration summaries.
        """
        if not self.iterations:
            return None
        full = self.get_loop_status()
        return {
            "active": full.get("active", False),
            "mode": full.get("mode", "bounded"),
            "current_iteration": full.get("current_iteration", 0),
            "total_iterations": full.get("total_iterations", 0),
            "current_focus": full.get("current_focus", ""),
            "converging": full.get("converging"),
            "issue_trend": full.get("issue_trend", []),
            "force_stopped": full.get("force_stopped", False),
            "max_iterations_reached": full.get("max_iterations_reached", False),
        }

    def get_brief_status(self) -> dict:
        """Trimmed workflow status — optimized for "where am I, what's next?".

        Excludes the firehose fields that full status dumps on every call:
        - full instruction text (pointer to wf_state() instead)
        - tasks_in_state (full task dicts)
        - recent_reflections (pointer to wf_status(mode='full'))
        - loop.iterations (full per-iteration history)

        Keeps the small signals the model needs to orient: current state,
        task/gate/loop counts, transition readiness, verification summary.
        """
        if not self.is_loaded:
            return {
                "loaded": False,
                "message": "No workflow loaded. Run /auto-auto from the auto-auto "
                "project to design one, or place a config.json in .workflow/",
            }

        transitions = self.get_available_transitions()
        transition_status = {}
        for t_name in transitions:
            allowed, reasons = self.check_transition_requirements(t_name)
            transition_status[t_name] = {
                "allowed": allowed,
                "blockers": reasons if not allowed else [],
            }

        all_tasks = list(self.tasks.values())
        task_summary = {
            "total": len(all_tasks),
            "pending": len([t for t in all_tasks if t.status == TaskStatus.PENDING]),
            "in_progress": len([t for t in all_tasks if t.status == TaskStatus.IN_PROGRESS]),
            "done": len([t for t in all_tasks if t.status == TaskStatus.DONE]),
        }

        v_plan = self.get_verification_plan()
        v_pending = self.get_pending_checks()
        verification_summary = None
        if v_plan:
            verification_summary = {
                "strategy": v_plan.get("strategy", "unknown"),
                "total_checks": len(v_plan.get("checks", [])),
                "pending_checks": len(v_pending),
                "passed_checks": len(v_plan.get("checks", [])) - len(v_pending),
            }

        return {
            "loaded": True,
            "mode": "brief",
            "workflow": {
                "name": self.config.get("name", "unnamed"),
                "goal": self.config.get("goal", ""),
            },
            "current_state": self.current_state,
            "task_summary": task_summary,
            "transitions": transition_status,
            "verification": verification_summary,
            "loop": self._loop_summary(),
            "total_gates": len(self.gates),
            "gates_passed": len([g for g in self.gates if g.passed]),
            "hint": (
                "This is the BRIEF dashboard — small and cheap. Call "
                "wf_status(mode='full') for instruction text, reflections, and "
                "full loop history, or wf_state() for the current state's "
                "instruction only."
            ),
        }

    def get_resume_summary(self) -> dict:
        """Compaction-recovery view: 'where was I, what do I do next?'.

        Designed to be called at session start or after context compaction.
        Returns a single coherent payload with a human-readable narrative
        plus structured fields — the narrative is what the model reads to
        orient, the structured fields are what code can inspect.
        """
        if not self.is_loaded:
            return {
                "loaded": False,
                "message": "No workflow loaded. Nothing to resume.",
            }

        loop_summary = self._loop_summary()
        pending_checks = self.get_pending_checks()
        in_progress_tasks = [
            t for t in self.tasks.values() if t.status == TaskStatus.IN_PROGRESS
        ]
        pending_tasks = [
            t for t in self.tasks.values() if t.status == TaskStatus.PENDING
        ]
        next_action = self.compute_next_action()

        # Build the narrative
        lines: list[str] = []
        lines.append(
            f"You are in workflow '{self.config.get('name', 'unnamed')}' "
            f"(goal: {self.config.get('goal', '(no goal)')})."
        )
        lines.append(f"Current state: {self.current_state}.")

        if loop_summary:
            iter_str = (
                f"iteration {loop_summary['current_iteration']} of "
                f"{loop_summary['total_iterations']}"
            )
            mode_str = loop_summary["mode"]
            active_str = "active" if loop_summary["active"] else "closed"
            lines.append(
                f"Loop: {iter_str} ({mode_str}, {active_str})."
                + (
                    f" Focus: {loop_summary['current_focus']}."
                    if loop_summary.get("current_focus")
                    else ""
                )
            )
            if loop_summary.get("converging") is False:
                lines.append(
                    "⚠️  Not converging — remaining_issues count is not decreasing."
                )

        # Tasks
        if in_progress_tasks:
            t = in_progress_tasks[0]
            lines.append(f"In-progress task: [{t.id}] {t.name}.")
        if pending_tasks:
            lines.append(f"Pending tasks: {len(pending_tasks)}.")

        # Gates
        v_plan = self.get_verification_plan()
        if v_plan:
            total = len(v_plan.get("checks", []))
            passing = total - len(pending_checks)
            lines.append(f"Verification: {passing}/{total} checks passing.")
            if pending_checks:
                names = [c.get("criteria", "?") for c in pending_checks[:3]]
                more = (
                    f" (+{len(pending_checks) - 3} more)"
                    if len(pending_checks) > 3
                    else ""
                )
                lines.append(f"Pending checks: {', '.join(names)}{more}.")

        # Next action
        if next_action:
            lines.append("")
            lines.append(f"→ Next: {next_action['suggestion']}")

        return {
            "loaded": True,
            "narrative": "\n".join(lines),
            "current_state": self.current_state,
            "workflow_name": self.config.get("name", "unnamed"),
            "workflow_goal": self.config.get("goal", ""),
            "loop": loop_summary,
            "in_progress_task_count": len(in_progress_tasks),
            "pending_task_count": len(pending_tasks),
            "pending_checks": [
                c.get("criteria", "(unnamed)") for c in pending_checks
            ],
            "total_gates": len(self.gates),
            "gates_passed": len([g for g in self.gates if g.passed]),
            "next_action": next_action,
        }
