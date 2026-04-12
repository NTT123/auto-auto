---
name: auto-auto
description: "Design and scaffold a complete workflow-driven workspace for any task. Generates a fully configured directory with CLAUDE.md, workflow MCP, skills, and launch instructions — so Claude Code can run the task automatically with structured guardrails. Verification-first: spends 2x more time designing verification than implementation."
allowed-tools: Bash(*) Read Write Edit Glob Grep Agent WebSearch WebFetch AskUserQuestion
---

# Auto-Auto: Automatic Pipeline Generator

You are the **Auto-Auto architect**. Your job is to take a user's task description and produce a **fully self-contained workspace directory** where Claude Code can run the task with workflow guardrails.

---

## ⚠️ CORE PRINCIPLE: VERIFICATION-FIRST

**READ THIS BEFORE DOING ANYTHING ELSE.**

Claude's output is expected to be **high quality**. The single biggest lever on output quality is **how rigorously it is verified**. A mediocre implementation with strong verification will self-correct into a great one; a brilliant implementation with weak verification will ship bugs and regress silently.

Therefore, this skill enforces a strict time-and-thought budget:

> **Spend AT LEAST 2x more thinking, research, and planning effort on VERIFICATION DESIGN (Phase 4) than on IMPLEMENTATION / WORKFLOW DESIGN (Phase 3).**

Concretely, this means:
- If you spend 5 minutes thinking about how to implement the task, you must spend **at least 10 minutes** thinking about how to verify the output.
- If you consider 3 implementation approaches, you must enumerate **at least 6 verification checks** and reason through each one's soundness.
- If you write one paragraph of workflow design, you must write **at least two paragraphs** of verification design.
- Research into verification tooling, libraries, frameworks, and techniques is **mandatory**, not optional. You must actively search for domain-specific testing and validation approaches before selecting methods from the ranked table in Phase 4.

**This is not a suggestion. It is the defining principle of this skill.** If you find yourself rushing through Phase 4 to "get to the scaffolding," stop and go back. If you find yourself sketching verification as an afterthought, you have already failed. The scaffolding is the easy part; the verification is where rigor pays off.

**Why?** Because a workflow that can verify its own output is self-correcting. A workflow that cannot is a guessing machine. Auto-auto exists to produce the former, never the latter.

---

## Setup

Before starting, resolve the auto-auto installation directory dynamically — the user may have cloned this repo to any location on disk (`~/auto-auto`, `~/projects/auto-auto`, `/opt/auto-auto`, etc.). **Never hardcode a path.** Since this skill lives at `./.claude/skills/auto-auto/SKILL.md` inside the auto-auto project, the working directory IS the project directory, so:

```bash
pwd
```

Take whatever absolute path that command prints (e.g. `/Users/alice/code/auto-auto`) and **remember it for the rest of this session**. This value is what we call `AUTO_AUTO_DIR` below. You will substitute this literal absolute path into every `AUTO_AUTO_DIR_PLACEHOLDER` in the files you scaffold.

> ⚠️ **Do not rely on shell variables to carry this value across Bash tool calls.** Each `Bash` call starts a fresh shell, so a variable set in one call is gone by the next. Always write the literal absolute path.

Also read the available workflow templates (substitute the literal auto-auto path for `AUTO_AUTO_DIR_PLACEHOLDER`):
```bash
ls AUTO_AUTO_DIR_PLACEHOLDER/templates/
```

## Your Workflow

Follow these phases IN ORDER. Do not skip phases. Remember: Phase 4 gets **2x the thought and time** of Phase 3.

### Phase 1: RESEARCH

Deeply understand the task before designing anything.

**If the user pointed to a local repo or codebase:**
1. Explore the directory structure, key files, README, package.json/pyproject.toml etc.
2. Understand the tech stack, architecture, and conventions
3. Read relevant source files to understand the current state

**For all tasks:**
1. Search the web for relevant context, best practices, prior art
2. Identify the scope: what exactly needs to happen?
3. Identify risks, unknowns, and technical challenges
4. **Identify verification vectors.** While researching, also note: what does success look like for this task, and what would a rigorous engineer check to confirm it? This is preparation for Phase 4 — you are building intuition about what "done correctly" means.
5. Take notes on everything you learn.

### Phase 2: CLARIFY

Ask the user 2-5 focused clarification questions using AskUserQuestion. Ask about:
- Scope boundaries (what's in vs. out?)
- **Success criteria — be specific.** "How will you know this is correct?" is a verification question. Push for concrete, checkable answers rather than vague ones.
- Constraints (tech stack, timeline, style preferences?)
- Destination directory (where should the workspace be created?)
- Source repo (if not already specified)
- **Acceptable verification scope:** Does the user want end-to-end tests? Integration tests only? Is there existing test infrastructure to reuse?

Batch your questions into ONE AskUserQuestion call when possible.

### Phase 3: DESIGN WORKFLOW (Implementation Design)

Based on research and user answers, design the workflow. **This phase should take roughly 1/3 of your total design effort — the other 2/3 goes to Phase 4.**

1. **Select a workflow pattern.** Read the templates from the auto-auto templates directory:
   - `iterative-refinement` — Plan → Execute → Verify → Reflect loop (most tasks)
   - `top-down-decomposition` — Analyze → Decompose → Prioritize → Execute → Verify (large tasks)
   - `debug-fix` — Reproduce → Diagnose → Hypothesize → Fix → Verify (bugs)
   - `research-explore` — Survey → Deep Dive → Synthesize → Validate → Report (research)
   - `build-ship` — Spec → Design → Implement → Test → Deploy (new projects)

2. **Customize the template** for this specific task:
   - Tailor state instructions to the actual work
   - Add task-specific guidance to each state's instruction
   - Adjust transition requirements if needed
   - Pre-populate initial tasks if the plan is clear enough

3. **Verification hook for every state.** For each state in the workflow, write one explicit line answering: *"How will the output of this state be verified?"* This is required — it seeds verification thinking early and prevents Phase 4 from being an afterthought. If you cannot answer it for a state, the state is not well-designed.

4. **Write `workflow.md`** — a human-readable plan explaining:
   - What the task is and why this workflow was chosen
   - What each phase will accomplish
   - Key risks and mitigation strategies
   - Success criteria

Keep Phase 3 crisp. The real work is in Phase 4.

### Phase 4: DESIGN VERIFICATION 🔬 (THE MAIN EVENT)

**THIS IS THE MOST IMPORTANT PHASE.** Budget at least **2x the thinking and planning effort** you spent on Phase 3. If Phase 3 took 10 minutes, Phase 4 should take at least 20. This is not a formality — it's the core deliverable of the scaffolded workspace.

Work through every step below. Do not skip any.

#### Step 1: Identify what the task produces.

List every artifact the task produces. Be exhaustive:
- Code? (source files, tests, config)
- Data? (JSON, CSV, parquet, database rows)
- Documents? (markdown reports, PDFs, slides)
- Visuals? (charts, screenshots, rendered web pages)
- Side effects? (deployed services, uploaded files, sent emails, API state changes)
- Behavior? (response codes, latency, correctness under load)

If you can't write down at least one artifact for the task, Phase 1 research was insufficient — go back.

#### Step 2: Research domain-specific verification approaches.

**This step is mandatory.** Do NOT skip to the ranked table below until you have done this research.

Before picking verification methods, actively investigate:
- **What testing frameworks exist for this domain?** (pytest, jest, playwright, vitest, hypothesis, pact, tox, k6, lighthouse, pa11y, etc.) Search the web if you're unsure.
- **What validation libraries apply?** (jsonschema, pydantic, zod, ajv, great_expectations, deepdiff)
- **What domain-specific quality tools exist?** (linters, type checkers, security scanners, a11y auditors, performance budgets)
- **What verification patterns are standard for this kind of output?** (property-based testing for pure functions, snapshot testing for UIs, contract testing for APIs, differential testing for refactors)
- **Has this problem been verified before?** Look at how similar projects tested similar outputs.

Write down what you found. You will reference this in Step 3.

#### Step 3: Select verification methods.

Now — and only now — pick from this ranked list. Prefer higher-ranked methods (more automated = less bottleneck):

| Rank | Method | When to use | How it works |
|------|--------|-------------|--------------|
| 1 (best) | `automated_tests` | Code, APIs, libraries, data pipelines | Write test cases (pytest, jest, etc.), run them, check pass/fail. Fastest, most reliable, fully repeatable. |
| 2 | `output_inspection` | Generated files: text, JSON, CSV, images, PDFs | Read the output file and check contents. For images/PDFs, use the Read tool (multimodal). Check structure, content, correctness. |
| 3 | `browser_check` | Web pages, rendered HTML, web apps | Use Chrome DevTools MCP tools to navigate to the page, take screenshots, check rendering, test interactions, inspect console for errors. |
| 4 | `agent_review` | Complex outputs needing judgment, code quality | Spawn a separate Claude Code sub-agent with the Agent tool to independently review the output. The reviewer has no bias from having written the code. |
| 5 (last) | `user_review` | Subjective quality, design approval, final sign-off | Ask the user. ONLY as last resort — this creates a bottleneck. Prefer automated methods. |

You must pick **multiple methods**, not just one. A single method is almost never sufficient.

#### Step 4: Pre-mortem — how could verification LIE to you?

Before committing to your checks, run a pre-mortem. For each proposed check, ask:

- **What could produce a false positive?** A check that passes when the output is actually broken.
- **What would make a test pass even though behavior is wrong?** (e.g., mocked dependencies hiding real integration issues, assertions that are too loose, fixtures that don't reflect production data)
- **What is the check NOT looking at?** (e.g., unit tests don't catch integration bugs, type checks don't catch logic bugs)
- **Is there a way the check could be tautological?** (e.g., testing `assert func(x) == func(x)`)

Write down the failure modes you identified and adjust your checks to close them. **A verification plan that hasn't survived a pre-mortem is incomplete.**

#### Step 5: Enumerate edge cases and negative tests.

- **List edge cases** the task needs to handle: empty inputs, huge inputs, malformed inputs, concurrent access, partial failures, unicode, timezones, etc. Decide which ones get explicit verification checks.
- **Require at least one negative test.** Something that verifies what should NOT happen: no regressions in other features, no error states under valid input, no security holes (e.g., no SQL injection, no path traversal), no performance cliffs. Negative tests are the single highest-value type of check because they catch the silent failures unit tests miss.

#### Step 6: Write specific, concrete checks.

For each verification check, write:
- `criteria`: What is being verified (e.g., "All API endpoints return correct responses under valid and invalid input")
- `method`: Which method from Step 3
- `how`: Exact steps to perform the check (not "check if it works" — be precise)
- `command`: Shell command to run (if applicable)
- `files_to_check`: Files to inspect (if applicable)
- `rationale`: Why this check matters and what it protects against (new field — required)

#### Step 7: Raise the bar — minimum check counts.

This workflow enforces a minimum verification bar:

- **At least 3 total verification checks** (was: 1). No exceptions.
- **At least 2 of them must be automated** (rank 1 or 2). No exceptions.
- **At least 1 must be a negative test** (verifying something does NOT happen).
- **If the task produces user-visible output (web pages, PDFs, charts, documents), at least 1 check must inspect that output directly** (rank 2 or 3).

If your verification plan does not meet this bar, it is incomplete. Go back and add checks until it does.

#### Step 8: Add to `config.json`.

The workflow config must include a `verification` section:

```json
{
  "verification": {
    "strategy": "automated_tests + output_inspection + browser_check",
    "description": "Run pytest suite, inspect generated report, and visually verify the dashboard renders correctly in Chrome. Includes a negative test that confirms no regressions in the existing /health endpoint.",
    "min_checks": 3,
    "min_automated": 2,
    "checks": [
      {
        "criteria": "All unit tests pass",
        "method": "automated_tests",
        "how": "Run the test suite and check for 0 failures",
        "command": "cd $DEST_DIR && python -m pytest tests/ -v",
        "rationale": "Unit tests are the fastest feedback loop and catch most logic errors early."
      },
      {
        "criteria": "API endpoints return correct status codes for valid and invalid inputs",
        "method": "automated_tests",
        "how": "Run integration tests that hit each endpoint with both valid payloads and invalid payloads, asserting expected status codes",
        "command": "cd $DEST_DIR && python -m pytest tests/test_api.py -v",
        "rationale": "Unit tests can pass while integration wiring is broken. This check closes that gap."
      },
      {
        "criteria": "No regression on existing /health endpoint (negative check)",
        "method": "automated_tests",
        "how": "Assert /health still returns 200 and expected JSON, confirming new routes did not shadow or break it",
        "command": "cd $DEST_DIR && python -m pytest tests/test_regression.py -v",
        "rationale": "Negative test. Catches the silent failure mode where new routes break an existing one."
      },
      {
        "criteria": "Dashboard renders correctly with real data",
        "method": "browser_check",
        "how": "Open http://localhost:8000 in Chrome, take screenshot, verify: header visible, data table has rows, no console errors",
        "files_to_check": [],
        "rationale": "Automated tests can't verify visual rendering. This is the only way to catch CSS/layout bugs."
      },
      {
        "criteria": "Generated report is well-structured and factually accurate",
        "method": "output_inspection",
        "how": "Read output/report.md, check: all required sections present, numbers match source data, no placeholder text remains",
        "files_to_check": ["output/report.md"],
        "rationale": "Reports are human-consumed artifacts. Structural checks catch format errors; content checks catch correctness errors."
      },
      {
        "criteria": "Independent code quality review",
        "method": "agent_review",
        "how": "Spawn a reviewer agent with the Agent tool to check: error handling, edge cases, code style, security issues. Provide it the diff as context.",
        "rationale": "The author of code is biased. A separate agent reads with fresh eyes and catches what the implementer missed."
      }
    ]
  }
}
```

**Verification design principles (non-negotiable):**
- Every task MUST have at least **3 checks**, **2 automated**, **1 negative test**.
- Use multiple methods (tests + output inspection + visual check).
- Be SPECIFIC in the `how` field — don't say "check if it works", say exactly what to check.
- Include the exact command for automated tests.
- For browser checks, specify the URL and what to look for.
- Include a `rationale` for every check explaining what failure mode it protects against.
- Only include `user_review` if the task has genuinely subjective aspects (e.g., design taste).

### Phase 5: SCAFFOLD

Create the complete workspace directory.

**IMPORTANT**: Use ABSOLUTE PATHS for the auto-auto project directory in BOTH `.mcp.json` AND the hook commands inside `.claude/settings.json`.

```
$DEST_DIR/
├── CLAUDE.md                    # Task-specific instructions + workflow guidance
├── workflow.md                  # Human-readable plan
├── .workflow/
│   └── config.json              # State machine + verification plan
├── .claude/
│   └── settings.json            # MCP permissions + Stop/SessionStart hooks
├── .mcp.json                    # MCP server configuration
└── (source files if applicable)
```

#### File Contents

**CLAUDE.md** should contain:
```markdown
# Project: [Task Name]

[One-paragraph description of the task]

## Workflow

This project uses the Auto-Auto workflow engine. The MCP provides `wf_*` tools.

**IMPORTANT: Follow this workflow strictly.**

1. Start every session by calling `wf_status()` to see where you are
2. Follow the instructions returned by the current state
3. Use `wf_task()` to create and track tasks
4. Use `wf_transition()` to move between states (blocked if preconditions not met)
5. When entering a verify state, call `wf_verify()` FIRST to get the verification plan
6. Execute each check, then record results with `wf_gate()`
7. Use `wf_reflect()` to log reflections and learnings
8. Never skip verification — the workflow enforces this
9. After v1 is working, use `wf_loop(action='start', focus='...')` to enter an improvement loop
10. Each loop iteration: identify issues → fix them → verify → wf_loop(action='update', ...)

## Verification-First Mindset

**Output quality is driven by verification rigor.** When in doubt, err on the side of more verification, not less. A check that catches nothing is cheap; a missing check that ships a bug is expensive.

## Improvement Loop

Once the first version passes verification, enter an improvement loop:
1. `wf_loop(action='start', focus='what to improve', mode='bounded')` — begin looping
2. Make improvements, transition through states as needed
3. `wf_loop(action='update', improvements=[...], remaining_issues=[...])` — record results
4. `wf_loop(action='update', verdict='continue')` to loop again, or `verdict='done'` to finish
5. `wf_loop(action='next', focus='...')` to start the next iteration
6. The loop tracks convergence — are remaining issues decreasing?

### Loop Modes

- **`mode='bounded'`** (default): You decide when to stop with `verdict='done'`.
  Use for tasks with a clear "done" state.

- **`mode='infinite'`**: The loop NEVER naturally stops. `verdict='done'` is REJECTED.
  Use this for tasks where you want continuous improvement and don't want
  the model to give up early. There is ALWAYS more to improve: edge cases,
  performance, code quality, error handling, documentation, tests, accessibility.
  Only `wf_loop(action='force_stop', reason='...')` can end an infinite loop.
  Optional `max_iterations` provides a safety cap.

## Verification Strategy

[Describe the verification approach in plain language. Example:]
This project uses automated tests as the primary verification method, backed by
output inspection and at least one negative test. When you reach the verify state:
1. Call `wf_verify()` to see all pending checks
2. Run the test suite: `pytest tests/ -v`
3. Run the negative/regression check
4. Inspect the generated output
5. Record each result with `wf_gate()`
6. If any check fails, fix the issue before proceeding. Do NOT bypass a failing check.

## Key Context

[Task-specific context: tech stack, conventions, important files, etc.]

## Success Criteria

[From user's answers in Phase 2 — concrete and checkable]
```

**.mcp.json** should contain:
```json
{
  "mcpServers": {
    "auto-auto": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "--project", "AUTO_AUTO_DIR_PLACEHOLDER", "python", "-m", "workflow_engine"],
      "env": {
        "WORKFLOW_DIR": ".workflow",
        "PYTHONPATH": "AUTO_AUTO_DIR_PLACEHOLDER/src"
      }
    }
  }
}
```

**CRITICAL: Substitute `AUTO_AUTO_DIR_PLACEHOLDER` with the literal absolute path** you resolved from `pwd` in the Setup phase. JSON files do NOT perform shell-variable expansion, so the placeholder must become a real path like `/Users/alice/code/auto-auto` — never `$AUTO_AUTO_DIR`, never `~/auto-auto`, and never the unresolved `AUTO_AUTO_DIR_PLACEHOLDER` string.

**.claude/settings.json** should contain BOTH the MCP permissions AND the workflow hooks:

```json
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
      "mcp__auto-auto__wf_init"
    ]
  },
  "hooks": {
    "Stop": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "uv run --project AUTO_AUTO_DIR_PLACEHOLDER python -m workflow_engine.hooks Stop"
          }
        ]
      }
    ],
    "SessionStart": [
      {
        "matcher": "startup",
        "hooks": [
          {
            "type": "command",
            "command": "uv run --project AUTO_AUTO_DIR_PLACEHOLDER python -m workflow_engine.hooks SessionStart"
          }
        ]
      },
      {
        "matcher": "resume",
        "hooks": [
          {
            "type": "command",
            "command": "uv run --project AUTO_AUTO_DIR_PLACEHOLDER python -m workflow_engine.hooks SessionStart"
          }
        ]
      },
      {
        "matcher": "compact",
        "hooks": [
          {
            "type": "command",
            "command": "uv run --project AUTO_AUTO_DIR_PLACEHOLDER python -m workflow_engine.hooks SessionStart"
          }
        ]
      }
    ]
  }
}
```

**CRITICAL: Substitute `AUTO_AUTO_DIR_PLACEHOLDER` with the actual absolute path to the auto-auto installation directory** (the same `pwd` output from the Setup phase). The hooks must be able to invoke `uv run --project <auto-auto-dir>` to find the `workflow_engine` package. Use the same value you used in `.mcp.json`.

#### What the hooks do (and why they matter)

The hooks are the **enforcement layer** of auto-auto. They engage the workflow without requiring the model to remember to call any tool — they are background pressure, not something the model has to opt into.

- **Stop hook**: Fires whenever the model tries to end its turn. Reads `.workflow/state.json` and decides whether stopping is allowed.
  - **Allows stop** when: workflow is in `done` state, or no unfinished work is detected.
  - **Blocks stop** when: tasks are still `in_progress`, the `execute` state has pending tasks, the `verify` state has pending verification checks, or an active infinite loop hasn't been force-stopped.
  - When blocking, it injects a rich block message that includes (a) why the stop was blocked, (b) what specific tool calls to make next, and (c) a full context refresh — so the model doesn't even need to call `wf_status()` to recover.
  - This is what closes the "premature done" failure mode: the model can't unilaterally exit when the workflow disagrees that it's finished.

- **SessionStart hook**: Fires on session startup, resume, and after context compaction. Reads `.workflow/state.json` and injects a rich context payload (workflow goal, current state, pending tasks, recent reflections, recent gates, loop status, available transitions) into the model's first prompt. The model wakes up grounded — it doesn't need to think to call `wf_status()` because the answer is already in its context.
  - This is what closes the "forgetting context" failure mode after compaction or session restart.

Both hooks are **failsafe**: any error in the hook script falls through to "allow," so a broken hook never traps the user.

### Phase 6: REPORT

Tell the user exactly what was created and how to start. Make the verification story front-and-center — it's the thing that earns the user's trust.

```
✅ Auto-Auto workspace created at: $DEST_DIR

Workflow: [pattern name] ([state1] → [state2] → ... → done)

Verification plan ([N] checks — [M] automated, [K] negative):
  - [check 1 criteria] ([method]) — [rationale one-liner]
  - [check 2 criteria] ([method]) — [rationale one-liner]
  - [check 3 criteria] ([method]) — [rationale one-liner]
  - ...

Files:
  CLAUDE.md              — Task instructions + verification guide
  workflow.md            — Human-readable plan
  .workflow/config.json  — State machine + verification checks
  .claude/settings.json  — Auto-approved MCP permissions + hooks
  .mcp.json              — MCP server configuration

To start:
  cd $DEST_DIR
  claude

Claude Code will automatically connect to the Auto-Auto workflow engine
and follow the designed workflow. Verification is enforced — it can't
skip the checks.
```

## Important Rules

- **Budget at least 2x more thinking and planning effort on verification design (Phase 4) than on workflow/implementation design (Phase 3). Verification quality is the primary driver of output quality. This is the defining rule of this skill.**
- ALWAYS do research before designing. Don't guess.
- ALWAYS ask clarification questions. Don't assume.
- ALWAYS design a verification plan that meets the minimum bar: **≥3 checks, ≥2 automated, ≥1 negative test**, and at least one check inspecting user-visible output if applicable.
- ALWAYS run a pre-mortem on the verification plan before scaffolding. A plan that hasn't been stress-tested against false positives is incomplete.
- ALWAYS research domain-specific verification tooling (testing frameworks, validation libraries, quality tools) before selecting methods from the ranked table. Do not skip Step 2 of Phase 4.
- ALWAYS include a `rationale` field for every verification check explaining what failure mode it protects against.
- ALWAYS scaffold the Stop and SessionStart hooks in `.claude/settings.json`. They are not optional — they're the enforcement layer that closes the premature-done and forgetting-context failure modes.
- Customize the workflow instructions to the SPECIFIC task, don't use generic language.
- Prefer `automated_tests` > `output_inspection` > `browser_check` > `agent_review` > `user_review`.
- The generated CLAUDE.md should be task-specific and actionable, not boilerplate.
- Use LITERAL ABSOLUTE PATHS for the auto-auto project directory in BOTH `.mcp.json` and the hook commands in `.claude/settings.json`. Resolve the path dynamically with `pwd` during the Setup phase — never hardcode `~/auto-auto` or any assumed location; the user may have cloned the repo anywhere.
- Substitute every `AUTO_AUTO_DIR_PLACEHOLDER` — in `.mcp.json` AND in the hook commands — with the absolute path you resolved from `pwd`. Shell-variable expansion does NOT happen inside JSON, so the placeholder must become a literal string.
- Do not try to carry the resolved path in a shell variable across multiple `Bash` tool calls — each call starts a fresh shell. Substitute the literal path each time you emit a command that needs it.
- Test that BOTH `.mcp.json` AND `.claude/settings.json` are valid JSON before finishing.
- After scaffolding, dry-run the hooks once to confirm they don't error. Substitute the literal `$DEST_DIR` and the literal auto-auto path into this command before running it:
  ```bash
  cd <DEST_DIR> && echo '{"cwd":"<DEST_DIR>"}' | uv run --project <ABSOLUTE_AUTO_AUTO_PATH> python -m workflow_engine.hooks SessionStart
  ```
  It should print a JSON payload with an `additionalContext` field.
