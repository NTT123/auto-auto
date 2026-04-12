# Auto-Auto — Build Plan

**Auto-Auto**: Automatic pipeline to generate automatic pipelines for any task.

## Architecture (Revised)

```
User: "I need to build X"
          │
          ▼
┌──────────────────┐
│  /auto-auto      │  ← Claude Code skill
│  (the architect) │
│                  │
│  1. Deep research│
│  2. Ask user Qs  │
│  3. Design workflow
│  4. Scaffold dest│
│     workspace    │
│  5. Generate     │
│     launch script│
└────────┬─────────┘
         │ creates
         ▼
┌──────────────────────────────────────────┐
│  Destination Workspace ($DEST_DIR/)      │
│                                          │
│  CLAUDE.md          ← task-specific      │
│  workflow.md        ← human-readable plan│
│  .workflow/                              │
│    config.json      ← state machine def  │
│    state.json       ← persisted state    │
│  .claude/                                │
│    settings.json    ← MCP server config  │
│    skills/                               │
│      workflow/SKILL.md ← in-session skill│
│  start.sh           ← launch script     │
└──────────────────────────────────────────┘
         │
         │ start.sh boots Claude Code with
         │ auto-auto MCP server attached
         ▼
┌──────────────────────────────────────────┐
│  Claude Code session                     │
│  + auto-auto MCP (wf_* tools)           │
│  + CLAUDE.md with workflow instructions  │
│  + /workflow skill for in-session use    │
│                                          │
│  Model follows the state machine,        │
│  uses wf_* tools to track progress,      │
│  gets blocked if it tries to skip steps  │
└──────────────────────────────────────────┘
```

## Progress

- [x] Task 1: Project structure and plan
- [x] Task 2: Build MCP server core (engine.py + server.py, 8 tools, 26 tests passing)
- [ ] Task 3: Build /auto-auto skill (SKILL.md) — the architect
- [ ] Task 4: Built-in workflow templates (JSON)
- [ ] Task 5: Workspace scaffolding + launch script generation
- [ ] Task 6: End-to-end testing
- [ ] Task 7: README and setup instructions

## MCP Server (DONE)

8 tools: `wf_status`, `wf_state`, `wf_next`, `wf_transition`, `wf_task`, `wf_gate`, `wf_reflect`, `wf_init`

State machine engine with:
- Enforced preconditions (all_tasks_done, all_tasks_defined, gate_passed, has_reflection)
- Task management (create/update/done/list with subtasks)
- Verification gates (criteria + evidence + pass/fail)
- Reflections (persisted, timestamped)
- Transition history
- Full persistence to .workflow/state.json

## Skill Design (/auto-auto)

The skill is invoked as `/auto-auto <task description>`.

### Skill Workflow:
1. **Research**: Deep-research the task — understand scope, requirements, dependencies
2. **Clarify**: Ask user clarification questions if needed
3. **Design**: Select/customize a workflow pattern for this specific task
4. **Scaffold**: Create the destination workspace with:
   - `CLAUDE.md` — task-specific instructions + workflow guidance
   - `workflow.md` — human-readable plan
   - `.workflow/config.json` — state machine definition
   - `.claude/settings.json` — MCP server configuration
   - `start.sh` — script to launch Claude Code with everything wired up
5. **Report**: Show user what was created and how to start

## Workflow Templates

| Template | Pattern | States |
|----------|---------|--------|
| iterative-refinement | PLAN → EXECUTE → VERIFY → REFLECT → (loop) | plan, execute, verify, reflect, done |
| top-down-decomposition | ANALYZE → DECOMPOSE → PRIORITIZE → [EXECUTE → VERIFY]* | analyze, decompose, prioritize, execute, verify, done |
| debug-fix | REPRODUCE → DIAGNOSE → HYPOTHESIZE → FIX → VERIFY | reproduce, diagnose, hypothesize, fix, verify, done |
| research-explore | SURVEY → DEEP_DIVE → SYNTHESIZE → VALIDATE | survey, deep_dive, synthesize, validate, report |
| build-ship | SPEC → DESIGN → IMPLEMENT → TEST → DEPLOY | spec, design, implement, test, deploy, done |
