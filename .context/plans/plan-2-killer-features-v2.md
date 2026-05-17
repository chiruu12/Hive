# Plan 2 v2: Killer Features — Updated After Provider Refactor

## What Changed Since Plan 2 v1

Major refactoring happened on `refactor/polish-providers-and-tests` (15 commits ahead of main):

**Done (was in Plan 1, now complete):**
- ✅ Provider architecture: 6 providers (Anthropic, OpenAI, Groq, Fireworks, Ollama, LMStudio) with BaseProvider ABC + tier presets (lite/standard/pro)
- ✅ Python API: `src/hive/api.py` — `Hive` class with init/spawn/start/stop/status/nudge/kill/inspect
- ✅ Plugin system: `src/hive/runtime/plugin_loader.py` — auto-discovers Toolkit subclasses from `.hive/plugins/`
- ✅ CI: `.github/workflows/ci.yml` configured
- ✅ Docs: `docs/user-guide.md` (35KB), `docs/agent-guide.md` (20KB), 10 examples updated
- ✅ Runtime agent refactored: extracted methods, cleaner ReAct loop, cost/token budgets
- ✅ Tests: 321 passing (up from 122), 30+ new provider tests

**Codebase now:** 11,006 LOC, 73 Python files, 6 model providers, 29 test files

**Still TODO from Plan 1:**
- Auto-resume on daemon restart
- Goal dependencies & subtasks
- `hive doctor` diagnostics
- Delegation wired as agent tool (engine exists, not exposed)

---

## Plan 2 Tasks (Updated)

### 2.1 Tool Synthesis — Agents Extend Themselves
**Priority:** Critical (no other framework does this) | **Est:** 3-4 hours

Agents write Python tools, validate them, hot-load into their toolkit.

- Agent calls `create_tool(name, description, code)` tool
- Writes to `.hive/tools/{name}.py`
- Validates: AST parse, smoke test, dangerous import blocklist (`os.system`, `subprocess.call`, `eval`, `exec`, `__import__`)
- Hot-loads via plugin_loader.py (already exists! just need synthesis entry point)
- Track provenance: which agent created which tool, when, why (store in SQLite)
- Persist across restarts

**Key insight:** The plugin system from Plan 1 is done. Synthesis just needs to write valid Toolkit .py files into the plugins dir. Half the work is already built.

**New files:** `src/hive/runtime/synthesis.py`
**Modify:** `src/hive/runtime/toolkits.py` (add SynthesisToolkit), `src/hive/daemon/loop.py` (reload scan)

**Verify:** Agent encounters task needing a tool it doesn't have → creates it → uses it → tool persists across restart

---

### 2.2 Agent Spawning by Agents
**Priority:** High | **Est:** 2-3 hours

Self-organizing teams. Agent spawns a temporary helper with a limited lifecycle.

- `spawn_helper(profile, objective, max_cycles)` tool
- Spawned agent gets temp ID, enters daemon loop
- Parent tracks child outcomes
- Auto-cleanup: child dies after max_cycles or goal completion
- Limit: max 3 spawned children per parent

**Leverages:** Profile system (working), daemon lifecycle (working), delegation engine (exists)

**New files:** None — add SpawnToolkit to `src/hive/runtime/toolkits.py`
**Modify:** `src/hive/daemon/loop.py` (lifecycle for spawned agents), `src/hive/agents/state.py` (add spawned_by, max_cycles)

---

### 2.3 Model Benchmarking Mode
**Priority:** High (viral potential) | **Est:** 3-4 hours

"Which AI lives the best life?" — same scenario, N models, compare.

- `hive benchmark <scenario> --models anthropic:lite,openai:standard,groq:lite`
- Uses the new tier preset syntax from the refactor
- Runs scenario N times per model
- Tracks: goal completion rate, avg steps, cost, suffering trajectory
- Generates Rich table comparison + JSON export
- Built-in benchmarks: "survive-50-cycles", "detective", "code-challenge"

**Key insight:** The new provider tiers (lite/standard/pro) make this trivial to set up. `Anthropic.lite()` vs `OpenAI.lite()` vs `Groq.lite()` — same tier, different providers.

**New files:** `src/hive/benchmark/` (runner.py, report.py), `scenarios/benchmarks/`
**Modify:** `src/hive/cli/main.py` (add benchmark command)

---

### 2.4 Polish Detective Demo + New Scenarios
**Priority:** High (the launch demo) | **Est:** 2-3 hours

Detective demo exists but has JSON parsing issues with some providers.

- Fix structured output fallback for Fireworks/Groq (JSON repair or regex extraction)
- Update to use new provider tier presets: `Anthropic.lite()`, `Fireworks.standard()`, etc.
- Add Rich formatted output during investigation (not just JSON dumps)
- Generate a "case report" at the end
- Make it one command: `hive demo detective`
- Add 1 new scenario: "startup pitch" (3 agents pitch startup ideas, oracle judges)

**Modify:** `scenarios/detective/run.py`, `src/hive/cli/main.py` (add demo command)
**New:** `scenarios/startup/`

---

### 2.5 Shareable HTML Run Reports
**Priority:** High (social sharing is how Hive goes viral) | **Est:** 3-4 hours

`hive export <run_id>` → standalone HTML file you can share on Twitter.

- Agent cards with profiles, goals, suffering bars
- Goal timeline (visual: generated → completed/abandoned)
- Suffering graph (SVG line chart per agent)
- Decision highlights (interesting tool calls, model reasoning)
- Cost breakdown table
- Dark theme, monospace, inline CSS/JS, no external deps
- Target: <500KB

**New files:** `src/hive/export/` (html.py, template.py)
**Modify:** `src/hive/cli/main.py` (add export command)

---

### 2.6 Web Browsing Toolkit
**Priority:** Medium | **Est:** 2-3 hours

Research agents need to browse. Without this they're trapped in local files.

- `web_fetch(url)` — GET, return markdown (HTML→markdown conversion)
- `web_search(query)` — DuckDuckGo instant answers or similar (no API key needed)
- Rate limiting: 10 requests per cycle
- Content truncation: max 4000 chars per fetch (LLM context budget)
- Uses httpx (already a dependency)

**Note:** beautifulsoup4 or similar needed for HTML→markdown. Add to deps.

**Modify:** `src/hive/runtime/toolkits.py` (add WebToolkit), `pyproject.toml` (add bs4)

---

### 2.7 Scheduled Goals — Agent Routines
**Priority:** Medium | **Est:** 2 hours

Persistent agents need routines. "Every N cycles, do X."

- `schedule_goal(objective, every_n_cycles)` tool
- Stored in SQLite (new `schedules` table)
- Daemon checks schedules each cycle, fires when due
- Show in `hive status`
- Agents can cancel schedules

**Modify:** `src/hive/memory/store.py` (schedules table), `src/hive/daemon/loop.py` (schedule check), `src/hive/runtime/toolkits.py` (ScheduleToolkit), `src/hive/cli/main.py` (display in status)

---

## Execution Order

```
2.1 Tool Synthesis        ← core differentiator, builds on plugin system
2.2 Agent Spawning        ← uses existing profiles + daemon lifecycle
2.4 Polish Detective Demo ← needs updated providers from refactor
2.3 Model Benchmarking    ← uses tier presets + detective demo
2.5 HTML Reports          ← uses logging/reader data from completed runs
2.6 Web Browsing          ← independent toolkit, no deps on above
2.7 Scheduled Goals       ← independent, touches store + daemon
```

2.6 and 2.7 can run in parallel. 2.1-2.5 are sequential.

---

## What This Unlocks

After Plan 2:
- Agents create tools, spawn helpers, run routines, browse the web
- `hive benchmark detective --models anthropic:lite,openai:lite,groq:lite` produces comparison
- Every run exports as a shareable HTML report
- Detective demo works flawlessly as a one-command showcase
- Framework is feature-complete for HN launch (Plan 3)
