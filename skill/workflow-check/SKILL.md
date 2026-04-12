---
name: workflow-check
description: "Quick check on workflow progress. Shows current state, pending tasks, and what to do next. Use when you need to re-orient."
allowed-tools: mcp__auto-auto__wf_status mcp__auto-auto__wf_next
---

# Workflow Check

Call `wf_status()` to get the full dashboard, then provide a concise summary:

1. **Where are we?** Current state and what it means
2. **What's done?** Tasks completed so far
3. **What's next?** Current state's instruction + pending tasks
4. **What's blocking?** Any transitions that are blocked and why

Keep the summary under 200 words. Be direct and actionable.
