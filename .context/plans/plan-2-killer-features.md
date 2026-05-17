# Plan 2: Killer Features — The "Holy Shit" Differentiators

## Why This Second

Plan 1 made Hive solid. Now make it remarkable. These features don't exist in
AutoGen, CrewAI, LangGraph, or smolagents. They're what make someone star the
repo after watching a 30-second demo.

Hive's pitch is "ant farm, not task runner." This plan delivers on that promise.

## Expected Outcome

After this plan, agents create their own tools, spawn helper agents, run on
schedules, browse the web, and compete in benchmarks. The detective demo works
flawlessly and produces shareable results. Every run generates a report you'd
want to post on Twitter.

---

## Tasks (in execution order)

### 2.1 Tool Synthesis — Agents Extend Themselves
**Priority:** Critical (core differentiator) | **Est:** 3-4 hours

No other framework does this. Agents write Python tools, validate them, and
hot-load them into their own toolkit — expanding their capabilities without
human intervention.

- Agent calls `create_tool(name, description, code)` tool
- Hive writes code to `.hive/tools/{name}.py`
- Validates: parse AST (syntax check), run basic smoke test, check for dangerous imports
- Hot-loads into agent's toolkit on next cycle
- Track provenance: which agent created which tool, when, why
- Safety: blocklist for `os.system`, `subprocess`, `eval`, network calls (configurable)
- Persist across restarts (tools in `.hive/tools/` survive daemon stop)

**Files:** `src/hive/runtime/synthesis.py` (new), `src/hive/runtime/toolkits.py` (add SynthesisToolkit), `src/hive/daemon/loop.py` (hot-reload scan)

**Verify:** Agent encounters a task it can't do → creates a tool → uses it → tool persists across restart

---

### 2.2 Agent Spawning by Agents — Self-Organizing Teams
**Priority:** High | **Est:** 2-3 hours

An agent can spawn a new agent to help with a subtask. The spawned agent has
a limited lifecycle (dies after completing its goal or after N cycles).

- Add `spawn_agent(profile, objective, max_cycles)` tool
- Spawned agent gets a temporary ID and enters the daemon loop
- Parent tracks spawned agents and their outcomes
- Auto-cleanup: spawned agents die after max_cycles or goal completion
- Limit: max 3 spawned agents per parent (prevent runaway spawning)

**Files:** `src/hive/runtime/toolkits.py` (add SpawnToolkit), `src/hive/daemon/loop.py` (lifecycle management), `src/hive/agents/state.py` (add spawned_by, max_cycles fields)

**Verify:** Coder agent gets complex task → spawns tester agent → tester validates code → tester dies → coder continues

---

### 2.3 Scheduled Goals — Agent Routines
**Priority:** High | **Est:** 2 hours

Persistent agents need routines. "Every morning, check for new issues."
"Every hour, review the codebase." "Every 10 cycles, write a status report."

- Add `schedule_goal(objective, every_n_cycles, start_after_cycle)` tool
- Stored in SQLite with next_fire_cycle
- Daemon checks schedules each cycle, fires goals when due
- Agent can cancel or modify schedules
- Display in `hive status`: show upcoming scheduled goals

**Files:** `src/hive/memory/store.py` (add schedules table), `src/hive/daemon/loop.py` (schedule check), `src/hive/runtime/toolkits.py` (add ScheduleToolkit), `src/hive/cli/main.py` (display in status)

**Verify:** Agent schedules a goal for every 5 cycles → runs autonomously → shows in status

---

### 2.4 Model Benchmarking Mode
**Priority:** High (viral potential) | **Est:** 3-4 hours

"Which AI lives the best life?" — same scenario, different models, compare.
Built-in A/B testing for LLMs through agent behavior.

- `hive benchmark <scenario> --models claude-sonnet,gpt-4o,deepseek-v3`
- Runs the same scenario N times per model
- Tracks: goal completion rate, average steps, cost, suffering trajectory, decision quality
- Generates comparison report: table + narrative
- Export as JSON for further analysis
- Built-in scenarios: "survive 100 cycles", "solve the mystery", "build a project"

**Files:** `src/hive/cli/main.py` (benchmark command), `src/hive/benchmark/` (new module: runner.py, report.py, scenarios/), `scenarios/benchmarks/` (built-in benchmark configs)

**Verify:** `hive benchmark detective --models claude-haiku,deepseek-v3` produces a comparison table

---

### 2.5 Polish Detective Demo
**Priority:** High (the launch demo) | **Est:** 2-3 hours

The detective demo exists but has issues (Kimi/Fireworks JSON parsing fails).
Make it flawless and produce beautiful output.

- Fix JSON parsing for all model providers (structured output fallback)
- Add Rich formatted output during the investigation (not just JSON results)
- Generate a "case report" at the end: who accused whom, confidence levels, reasoning chains
- Make it runnable in one command: `hive demo detective`
- Add 1-2 more scenarios: "startup pitch competition", "code review debate"

**Files:** `scenarios/detective/run.py`, `src/hive/cli/main.py` (add demo command), `scenarios/startup/` (new), `scenarios/debate/` (new)

**Verify:** `hive demo detective` runs cleanly with any 2+ models, produces a readable case report

---

### 2.6 Shareable Run Reports — HTML Export
**Priority:** High (social sharing) | **Est:** 3-4 hours

Every run should produce a standalone HTML page you can share on Twitter/Reddit.
"Look what my agents did" — this is how Hive goes viral.

- `hive export <run_id>` generates a self-contained HTML file
- Includes: agent profiles, goal timeline, suffering graphs (SVG), decision highlights, tool call log, final narrative
- Clean design: dark theme, monospace, minimal JS (inline everything)
- Optionally include cost breakdown and model comparison
- File size target: <500KB (no external deps)

**Files:** `src/hive/export/` (new module: html.py, templates/), `src/hive/cli/main.py` (export command)

**Verify:** Run a session → `hive export <id> -o report.html` → open in browser → looks good, shareable

---

### 2.7 Web Browsing Toolkit
**Priority:** Medium | **Est:** 2-3 hours

Research agents need to browse the web. Without this, agents are trapped in local files.

- Tools: `web_fetch(url)` (GET, return text), `web_search(query)` (via DuckDuckGo or similar)
- HTML → markdown conversion (strip tags, keep structure)
- Rate limiting (max 10 requests per cycle)
- Respect robots.txt
- No auth/cookies — simple read-only browsing

**Files:** `src/hive/runtime/toolkits.py` (add WebToolkit), add `httpx` + `beautifulsoup4` to deps

**Verify:** Research agent searches for "Python asyncio best practices" → reads top result → stores summary in memory

---

## Completion Criteria

- [ ] Agents create tools that persist and work across restarts
- [ ] Agents spawn helper agents that auto-cleanup
- [ ] Scheduled goals fire on time
- [ ] `hive benchmark` compares models on identical scenarios
- [ ] Detective demo runs flawlessly with `hive demo detective`
- [ ] `hive export` produces shareable HTML reports
- [ ] Research agents can browse the web
