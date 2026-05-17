# Hive Repo — Incomplete Areas Audit

## Repository Snapshot

- **Branch**: `dev` (ahead of `origin/dev` by 1 commit)
- **Untracked artifacts**: `logs/`, `scenarios/detective/results/run-*.json`
- **Tests**: `uv run pytest` — 122 passed
- **Lint**: `uv run ruff check src tests scenarios` — 7 errors (all in `scenarios/`)
- **Types**: `uv run mypy src` — 82 errors in 24 files (65 checked)

---

## Findings

### 1. Packaging: YAML data files excluded from wheel

**Severity**: High
**Files**: `pyproject.toml`, `profiles/*.yaml`, `models.yaml`, `dist/hive_agent-0.1.0-py3-none-any.whl`

`pyproject.toml` has no `[tool.setuptools.package-data]` or equivalent config. The existing wheel at `dist/` contains zero `.yaml` files. This means `pip install hive-agent` from the wheel works only when run from the project root (where `profiles/` and `models.yaml` are in CWD).

Code has fallback logic (`profile.py:10-19` checks CWD then `importlib.resources`, `registry.py:11-13` checks CWD then relative path), but neither fallback works from an arbitrary install location.

**Affected files**:
- `profiles/coder.yaml`, `oracle.yaml`, `researcher.yaml`, `reviewer.yaml`, `tester.yaml`
- `models.yaml` (model registry with pricing/routing)

**Fix**: Add package-data config to `pyproject.toml` to bundle YAML files, or copy them into `src/hive/` and adjust paths.

**Verify**: `uv build && unzip -l dist/*.whl | grep yaml`

---

### 2. README architecture section references deleted module

**Severity**: Low
**File**: `README.md:57`

Line 57 shows `├── execution/        # Tool system` in the architecture diagram, but `src/hive/execution/` was deleted in this branch. The `runtime/` module that replaced it is not shown. Line 47 says `├── agents/  # Agent runtime` which is vague.

**Fix**: Update the architecture tree to replace `execution/` with `runtime/` and add a line for `context.py`.

**Verify**: `ls src/hive/ | sort` and compare with README.

---

### 3. Launcher scripts

**Severity**: None (not a real issue)

`scripts/start.sh` and `scripts/stop.sh` exist and reference `hive.daemon.server`, which still exists. No broken imports or deleted module references. This was a false positive from the other agent's checklist.

---

### 4. Mypy strict typing failures — 82 errors

**Severity**: Medium
**File**: `pyproject.toml` (mypy config at `[tool.mypy]` with `strict = true`)

Breakdown by error code:
| Code | Count | Description |
|------|-------|-------------|
| `type-arg` | 35 | Missing generic type args (`dict` → `dict[str, Any]`) |
| `no-untyped-call` | 17 | Calling untyped functions in typed context |
| `no-any-return` | 7 | Returning `Any` from typed function |
| `arg-type` | 6 | Wrong argument type (includes `WorldState \| None` issues) |
| `import-untyped` | 4 | Missing stubs (yaml) |
| `attr-defined` | 4 | Attribute not found on type |
| `union-attr` | 3 | Accessing attr on union without narrowing |
| `abstract` | 2 | Instantiating abstract class |
| `no-untyped-def` | 2 | Missing function annotation |
| `return-value` | 1 | Wrong return type |
| `assignment` | 1 | Incompatible assignment |

Most impactful clusters:
- **`daemon/loop.py`** (6 errors): `WorldState | None` passed where non-optional `WorldState` expected — real type-safety gap from the economy-toggle refactor
- **`interactions/runner.py`** (7 errors): Type mismatches with `GenerateResult` vs old `ScenarioResult`
- **`mcp/server.py`** (4 errors): Bare `dict` without type params

**Fix**: Address in priority order — `arg-type` and `union-attr` errors are real safety gaps; `type-arg` errors are annotation noise.

**Verify**: `uv run mypy src`

---

### 5. Persistent memory wrapper — SemanticMemory integration

**Severity**: Was Critical — now fixed
**Files**: `src/hive/runtime/memory.py`, `src/hive/memory/semantic.py`

Three bugs were fixed earlier in this session:
- Constructor arg order was reversed (`agent_name, hive_dir` → `hive_dir, agent_name`)
- Called non-existent `add_observation()` instead of `store()`
- Called non-existent `query()` instead of `search()`
- `clear()` didn't delete persisted data
- `store()` returned meaningless ID in semantic path

All fixed. No remaining issues.

**Verify**: `uv run pytest tests/runtime/test_agent.py -x`

---

### 6. Model availability detection — key-only check

**Severity**: Low
**Files**: `src/hive/runtime/providers.py:52-54`, `src/hive/runtime/providers.py:210-212`

Both `AnthropicRuntimeProvider.available` and `OpenAIRuntimeProvider.available` return `bool(api_key)` — they don't test connectivity. Invalid/revoked keys or network issues aren't detected until generation time.

This is standard practice for SDK wrappers (the old deleted providers did the same thing). Not a regression, and adding connectivity checks would introduce latency on startup. Acceptable as-is.

**Fix**: None needed. Could optionally add a `ping()`/`verify()` method for explicit health checks.

---

### 7. Runtime Agent doesn't use structured LogWriter

**Severity**: Medium
**Files**: `src/hive/runtime/agent.py`, `src/hive/logging/writer.py`, `src/hive/logging/models.py`

`Agent.run()` uses only Python `logging` (debug/error/warning). The structured logging infrastructure (`LogWriter` with `DecisionLog`, `ToolLog`, `CycleLog`, `GoalLog`) exists and is used by `ExistenceLoop` and the daemon, but the runtime `Agent` doesn't emit any structured logs.

This means tool calls, model generation metadata (tokens, cost, duration), and step-by-step traces from `Agent.run()` are invisible to the log analysis pipeline.

**Fix**: Accept an optional `LogWriter` in Agent constructor. Log `DecisionLog` after each `generate()` call and `ToolLog` after each tool execution.

**Verify**: Run a scenario and check `logs/` for agent-level structured entries.

---

### 8. Two parallel interaction APIs coexist

**Severity**: Low
**Files**: `src/hive/interactions/base.py`, `src/hive/interactions/runner.py`, `src/hive/interactions/exchange.py`

Two systems live in `interactions/`:
- **Old**: `Scenario`, `ScenarioRunner`, `InteractionPattern`, `MemoryStrategy`, `AgentSlot` — used by `scenarios/detective/run.py`
- **New**: `Participant`, `ExchangeRunner`, `ExchangeConfig`, `InteractionMessage` — used by tests and presets

Both are exported from `interactions/__init__.py`. The old system still works (provider calls were updated to `create_runtime_provider`). Neither is dead code — `ScenarioRunner` powers the detective scenario, `ExchangeRunner` is the new primary API.

**Fix**: Not urgent. When the old scenario system is no longer needed, remove it. Until then, coexistence is fine — they don't conflict.

---

### 9. Scenario lint issues — 7 ruff errors

**Severity**: Low
**File**: `scenarios/detective/run.py`, `scenarios/runtime_test.py`

All 7 errors are in `scenarios/` (zero in `src/`):
- 4x `E402` in `detective/run.py`: imports after `sys.path.insert` — necessary for standalone scripts
- 1x `F841` in `detective/run.py:288`: unused `correct_answer` variable
- 1x `F541` in `runtime_test.py:78`: f-string with no placeholders
- 1x `F841` in `runtime_test.py:88`: unused `expected` variable

The `E402` errors are inherent to the `sys.path` pattern and can be suppressed with `# noqa: E402`. The `F841` and `F541` are trivial cleanups.

**Fix**: Add `# noqa: E402` to the post-sys.path imports, remove unused variables, drop the stray `f` prefix.

**Verify**: `uv run ruff check scenarios/`

---

## Priority Summary

| # | Finding | Severity | Action |
|---|---------|----------|--------|
| 1 | YAML files excluded from wheel | High | Fix pyproject.toml packaging |
| 4 | 82 mypy errors (6 real type-safety gaps) | Medium | Fix arg-type/union-attr errors in daemon/loop.py and interactions/runner.py |
| 7 | Runtime Agent missing structured logging | Medium | Wire LogWriter into Agent |
| 2 | README stale architecture diagram | Low | Update tree |
| 8 | Dual interaction APIs | Low | Document; deprecate old when ready |
| 9 | 7 ruff errors in scenarios/ | Low | Quick cleanup |
| 3 | Launcher scripts | None | No issue found |
| 5 | PersistentMemory semantic bugs | None | Already fixed |
| 6 | Model availability key-only check | None | By design |
