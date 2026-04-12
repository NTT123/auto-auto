# Auto-Auto

**Automatic pipeline to generate automatic pipelines.**

Auto-Auto is a Claude Code skill + MCP server that:
1. Takes any task description
2. Researches it deeply (online + local codebase)
3. Designs a structured workflow (state machine) for that specific task
4. Scaffolds a complete workspace directory with everything pre-configured
5. So you can just `cd` in and run `claude` — the model follows the workflow automatically

## How It Works

```
You: /auto-auto Build a REST API for user management

Auto-Auto:
  1. Researches REST API best practices, your tech stack, etc.
  2. Asks you 3-4 clarification questions
  3. Picks "iterative-refinement" workflow, customizes it
  4. Creates ~/projects/user-api/ with:
     - CLAUDE.md (task-specific instructions)
     - .workflow/config.json (state machine)
     - .mcp.json (MCP server config)
     - .claude/settings.json (permissions)

You: cd ~/projects/user-api && claude

Claude Code:
  - Connects to Auto-Auto MCP server
  - Calls wf_status() → "You're in PLAN state"
  - Creates tasks, implements them, verifies...
  - Can't skip verification (transitions are enforced)
  - Reflects after each iteration
```

## Installation

```bash
git clone <this-repo>
cd auto-auto
./install.sh
```

Requirements:
- Python 3.12+ (via uv)
- [uv](https://docs.astral.sh/uv/) package manager
- Claude Code

## Usage

### From any Claude Code session:

```
/auto-auto <describe your task>
```

The skill will research, ask questions, design a workflow, and scaffold a workspace.

### Then run the task:

```bash
cd <generated-workspace>
claude
```

Claude Code will automatically connect to the workflow engine and follow the designed workflow.

## Workflow Templates

| Template | Pattern | Best For |
|----------|---------|----------|
| `iterative-refinement` | Plan → Execute → Verify → Reflect → loop | Most tasks: features, refactoring, tools |
| `top-down-decomposition` | Analyze → Decompose → Prioritize → Execute → Verify | Large, complex multi-component tasks |
| `debug-fix` | Reproduce → Diagnose → Hypothesize → Fix → Verify | Bug fixes, debugging, troubleshooting |
| `research-explore` | Survey → Deep Dive → Synthesize → Validate → Report | Research, evaluation, documentation |
| `build-ship` | Spec → Design → Implement → Test → Deploy | New projects, shipping features |

## MCP Tools

The workflow engine exposes 10 tools:

| Tool | Purpose |
|------|---------|
| `wf_status()` | Full dashboard — where am I, what's next? |
| `wf_state()` | Current state details + instructions |
| `wf_next()` | Available transitions + what's blocking them |
| `wf_transition(to, reason)` | Move to next state (blocked if preconditions not met) |
| `wf_task(action, ...)` | Create/update/list/complete tasks |
| `wf_verify()` | Get verification plan — what to check, how, what's left |
| `wf_gate(criteria, passed, evidence)` | Record verification results |
| `wf_reflect(content)` | Log reflections and learnings |
| `wf_loop(action, ...)` | Manage improvement loops with iteration tracking |
| `wf_init(config_json)` | Initialize workflow from JSON |

### Enforcement

**Transitions are enforced.** For example:
- Can't move from `execute` → `verify` until all tasks are done
- Can't move from `verify` → `done` until a gate check passes
- Can't skip the reflection step if the workflow requires it

### Hooks: enforcement that doesn't depend on the model cooperating

The MCP tools above all require the model to *call* them. Auto-Auto also installs two Claude Code hooks that engage the workflow **without** the model's cooperation — they're the background pressure that closes the unilateral-exit and forgetting-after-compaction failure modes.

| Hook | Fires when | What it does |
|------|-----------|--------------|
| `Stop` | Model tries to end its turn | Reads `.workflow/state.json`. If there are in-progress tasks, pending verification checks, or an active infinite loop, **blocks the stop** and returns a rich block message that names the unfinished work, tells the model what tool calls to make next, and includes a full context refresh. |
| `SessionStart` | Session startup, resume, or after context compaction | Reads `.workflow/state.json` and **injects a context payload** (workflow goal, current state, pending tasks, recent reflections, recent gates, loop status, available transitions) into the model's first prompt. The model wakes up grounded — no need to remember to call `wf_status()`. |

Both are scaffolded automatically by `/auto-auto` into `.claude/settings.json`. Both are **failsafe**: any internal error in the hook script falls through to "allow," so a broken hook never traps the user.

Why this matters: today's models are good at staying on track *within a single tool-call cycle*. Where they fail is at the boundaries — declaring done too early, forgetting decisions after a long arc, exiting before verification. The hooks are precisely that boundary layer. The Stop hook prevents the model from quietly exiting; the SessionStart hook prevents the model from waking up confused.

### Verification

Each workflow has a **verification plan** designed during scaffolding.
When entering a verify state, `wf_verify()` returns exactly what to check:

```
wf_verify() → {checks: [
  {criteria: "All tests pass", method: "automated_tests", command: "pytest tests/"},
  {criteria: "Dashboard renders", method: "browser_check", how: "Open localhost:8000..."},
]}
```

Methods ranked by automation (prefer higher):
1. `automated_tests` — run commands, check output
2. `output_inspection` — read/examine generated files
3. `browser_check` — Chrome DevTools inspection
4. `agent_review` — spawn independent reviewer
5. `user_review` — ask user (last resort)

### Improvement Loops

The most common real-world pattern: build v1, then **loop to improve**.

```
[Build v1: linear]               [Improve: loop]
PLAN → EXECUTE → VERIFY  →  wf_loop("start") →  EVALUATE → IMPROVE → VERIFY ─┐
                                                      ▲                         │
                                                      └── wf_loop("next") ──────┘
```

The loop system tracks:
- **Iteration count** — which pass are we on?
- **Focus** — what each iteration aims to improve
- **Improvements** — what got better each round
- **Remaining issues** — what's still to fix
- **Convergence** — are remaining issues decreasing? (detects going in circles)

```
wf_loop(action="status") → {
  active: true,
  mode: "bounded",
  current_iteration: 3,
  issue_trend: [5, 3, 1],  ← converging!
  converging: true,
  iterations: [{focus: "...", improvements: [...], remaining_issues: [...]}, ...]
}
```

### Loop Modes: Bounded vs Infinite

**Bounded mode (default)** — Model decides when to stop with `verdict='done'`.

**Infinite mode** — Model is PUSHED to keep going. `verdict='done'` is rejected.

```
wf_loop(action="start", focus="Polish", mode="infinite", max_iterations=20)
  ↓
"♾️ INFINITE LOOP STARTED. DO NOT STOP. Even if it looks good enough, there's
 always more to improve."

wf_loop(action="update", verdict="done")
  ↓
"♾️ verdict='done' was REJECTED. This is an infinite loop. Some ideas:
 harder edge cases, performance, error messages, more tests, refactoring,
 documentation, accessibility, polish. Pick something and keep going."

wf_loop(action="force_stop", reason="User wants to ship now")
  ↓
"♾️ Infinite loop force-stopped after 12 iterations."
```

Use infinite mode when:
- The model tends to give up too early
- There's no clear "done" — work can always be improved
- You want continuous refinement until externally stopped
- Polish/quality tasks with subjective standards

The optional `max_iterations` provides a safety cap to prevent runaway loops.

## Project Structure

```
auto-auto/
├── src/workflow_engine/
│   ├── engine.py          # State machine core (states, transitions, tasks, gates)
│   ├── server.py          # FastMCP server exposing wf_* tools
│   ├── hooks.py           # Claude Code Stop & SessionStart hook scripts
│   └── __main__.py        # Entry point
├── templates/             # Workflow template definitions (JSON)
│   ├── iterative-refinement.json
│   ├── top-down-decomposition.json
│   ├── debug-fix.json
│   ├── research-explore.json
│   └── build-ship.json
├── skill/
│   ├── auto-auto/SKILL.md      # The /auto-auto architect skill
│   └── workflow-check/SKILL.md  # Quick status check skill
├── tests/
│   ├── test_engine.py           # Engine unit tests
│   ├── test_mcp_tools.py        # MCP tool integration tests
│   ├── test_hooks.py            # Stop & SessionStart hook tests
│   ├── test_loop.py             # Loop / iteration tests
│   ├── test_infinite_loop.py    # Infinite-mode loop tests
│   ├── test_verification.py     # Verification plan tests
│   └── test_full_scaffold.py    # End-to-end scaffold + hook tests
├── install.sh             # One-command installer
├── plan.md                # Architecture and build plan
└── pyproject.toml         # Python project config
```

## How the State Machine Works

Each workflow is a directed graph of **states** with **transitions** between them.
Each transition can have **preconditions** that must be met before the model can proceed.

```
        ┌──────────────────────────────────────┐
        │                                      │
        ▼                                      │
    ┌──────┐     ┌─────────┐     ┌────────┐   │
    │ PLAN │────▶│ EXECUTE │────▶│ VERIFY │───┘
    └──────┘     └─────────┘     └────────┘
        ▲             │               │
        │             ▼               ▼
        │        ┌─────────┐     ┌───────┐
        └────────│ REFLECT │     │ DONE  │
                 └─────────┘     └───────┘
```

Preconditions:
- `all_tasks_defined` — at least one task exists
- `all_tasks_done` — every task is marked done
- `gate_passed` — a verification gate has passed
- `has_reflection` — a reflection has been logged

All state is persisted to `.workflow/state.json`, surviving context compaction and session restarts.

## Design Philosophy

Based on research from:
- [StateFlow](https://arxiv.org/html/2403.11322v1) — LLM task-solving as finite state machines
- [Blueprint First, Model Second](https://arxiv.org/abs/2508.02721) — Deterministic workflow, LLM as tool
- [Building Effective Agents](https://www.anthropic.com/research/building-effective-agents) — Anthropic's composable patterns
- [VMAO](https://arxiv.org/html/2603.11445v1) — Plan-Execute-Verify-Replan framework

Key insight: **The model performs dramatically better when it doesn't have to self-regulate its own workflow.** Auto-Auto provides the structure; the model provides the intelligence.
