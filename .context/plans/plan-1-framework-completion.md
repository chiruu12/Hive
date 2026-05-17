# Plan 1: Framework Completion — Make Hive Production-Quality

## Why This First

Hive has 9,700 LOC of working code but rough edges that would kill adoption.
Dev branch is 21 commits ahead of main. `hive watch` crashes. No auto-resume.
Delegation exists but isn't exposed. No programmatic API — only CLI.

A framework that doesn't feel solid doesn't get stars. This plan fixes that.

## Expected Outcome

After this plan, someone can `pip install hive-agent`, run agents for hours,
restart their machine, resume where they left off, extend Hive with custom tools,
and use it as a Python library — not just a CLI toy.

---

## Tasks (in execution order)

### 1.1 Merge dev → main + Fix Phase 1 Gaps
**Priority:** Critical | **Est:** 1-2 hours

- Merge dev (21 commits ahead) into main
- Fix `hive watch` async bugs (nested `asyncio.run()` in main.py:241-374)
- Fix priority mypy errors (`arg-type`, `union-attr` in daemon/loop.py, interactions/runner.py)
- Add `types-PyYAML` to dev deps
- Write integration test: daemon runs 3 cycles with mocked provider → asserts goals, suffering, events, persistence
- Update README architecture diagram (replace `execution/` with `runtime/`)

**Files:** `src/hive/cli/main.py`, `src/hive/daemon/loop.py`, `src/hive/interactions/runner.py`, `pyproject.toml`, `README.md`, `tests/test_daemon_integration.py`

**Verify:** `uv run pytest`, `uv run mypy src`, `hive watch` runs without crash

---

### 1.2 Auto-Resume on Daemon Restart
**Priority:** Critical | **Est:** 2-3 hours

"Persistent agents" is the core promise. Right now agents die on Ctrl+C and don't come back.

- On daemon stop: checkpoint all agent states (suffering, goals, identity, world) to SQLite
- On `hive start`: detect existing agents in DB, resume from last checkpoint
- Add `--fresh` flag to `hive start` for clean start (ignore saved state)
- Resume logic: reload profiles, restore suffering state, re-enter existence loop
- Handle stale goals: if a goal was mid-execution, mark it abandoned and let the agent generate a new one

**Files:** `src/hive/daemon/loop.py`, `src/hive/daemon/lifecycle.py` (new or extend), `src/hive/cli/main.py`, `src/hive/checkpoint.py`

**Verify:** Start daemon → let it run 5 cycles → Ctrl+C → `hive start` → agents resume with correct suffering levels and identities

---

### 1.3 Wire Delegation as an Agent Tool
**Priority:** High | **Est:** 1 hour

Delegation engine exists (`src/hive/agents/delegation.py`) but agents can't use it — it's not in any toolkit. Easy win.

- Create `DelegationToolkit` with tools: `delegate_task(agent_name, objective)`, `check_delegation(delegation_id)`, `list_peers()`
- Wire into daemon's tool injection so agents discover peers
- Delegation creates a goal in the target agent's queue

**Files:** `src/hive/runtime/toolkits.py` (add DelegationToolkit), `src/hive/daemon/loop.py` (inject toolkit)

**Verify:** Start 2 agents → one delegates to the other → target picks up the goal

---

### 1.4 Goal Dependencies & Subtasks
**Priority:** High | **Est:** 2-3 hours

Complex goals need decomposition. Currently goals are flat — no parent/child relationships.

- Add `parent_goal_id` and `subtasks` fields to goal schema in store
- When agent generates a goal that's too complex (model says so), auto-decompose into subtasks
- Subtask completion rolls up to parent
- Parent goal completes when all subtasks done (or abandons if any critical subtask fails)
- Display in `hive inspect`: show goal tree, not flat list

**Files:** `src/hive/memory/store.py` (schema), `src/hive/agents/existence.py` (decomposition), `src/hive/cli/main.py` (inspect display)

**Verify:** Agent generates complex goal → breaks into 2-3 subtasks → completes them → parent completes

---

### 1.5 Plugin System for Toolkits
**Priority:** High | **Est:** 2-3 hours

Hardcoded toolkits limit extensibility. Users should drop a Python file and agents get new tools.

- Scan `.hive/plugins/` and `plugins/` for Python files on daemon start
- Each plugin exports a `Toolkit` subclass (already the right abstraction)
- Auto-register discovered toolkits into the agent's tool set
- Hot-reload: detect new plugins each cycle without daemon restart
- Document the plugin contract: "Create a class extending Toolkit, put it in plugins/"

**Files:** `src/hive/runtime/plugin_loader.py` (new), `src/hive/daemon/loop.py` (plugin discovery), `docs/plugins.md` (new)

**Verify:** Drop a custom toolkit .py into plugins/ → agent discovers and uses the new tools

---

### 1.6 Programmatic Python API
**Priority:** High | **Est:** 2-3 hours

Framework users need a Python API, not just CLI. Without this, Hive can't be a dependency.

```python
from hive import Hive

h = Hive()
h.init()
agent = h.spawn("coder")
h.nudge(agent, "write a sorting algorithm")
h.start(cycles=10)  # run 10 cycles and stop
print(h.status())
report = h.inspect(h.last_run_id)
```

- Wrap existing CLI logic into a `Hive` class
- Expose: `init()`, `spawn()`, `start()`, `stop()`, `status()`, `nudge()`, `inspect()`, `kill()`
- Add `start(cycles=N)` for bounded runs (useful for scripts/tests)
- Export from package root: `from hive import Hive`

**Files:** `src/hive/api.py` (new), `src/hive/__init__.py` (export)

**Verify:** Python script that spawns an agent, runs 3 cycles, and prints status — no CLI involved

---

### 1.7 `hive doctor` Diagnostics
**Priority:** Medium | **Est:** 1 hour

- Check: API keys present (Anthropic, OpenAI), local models reachable (Ollama, LM Studio)
- Check: .hive/ directory health, SQLite integrity, disk space
- Check: Python version, dependency versions
- Report: green/yellow/red status for each check
- Suggest fixes for common issues

**Files:** `src/hive/cli/main.py` (add command), `src/hive/daemon/diagnostics.py` (new)

**Verify:** `hive doctor` with missing API key shows yellow warning + fix suggestion

---

## Completion Criteria

- [ ] Dev merged to main, all tests pass
- [ ] `hive watch` runs without crashing
- [ ] Daemon resume works across restarts
- [ ] Agents can delegate to each other via tools
- [ ] Goals can have subtasks
- [ ] Custom toolkits load from plugins/
- [ ] `from hive import Hive` works as a Python API
- [ ] `hive doctor` reports system health
- [ ] Mypy errors reduced to annotation noise only (zero arg-type/union-attr)
