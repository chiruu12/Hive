# Phase 1 — Remaining Work

## Status Audit (2026-05-11)

Most of Phase 1 is done. Tests pass (122/122), lint is clean, YAML packaging is fixed,
`replay`, `inspect`, `nudge`, `runs`, `status` all work. Runtime Agent has structured
logging wired in.

### What's left

| # | Task | Severity | Est. |
|---|------|----------|------|
| 1 | Fix `hive watch` async bugs | Critical | 30 min |
| 2 | Fix mypy type errors | Medium | 45 min |
| 3 | Update README architecture diagram | Low | 5 min |
| 4 | Integration test for daemon loop | Medium | 30 min |

---

## Task 1: Fix `hive watch` — Async Bugs

**File:** `src/hive/cli/main.py` lines 241-374

**Problem:** `_build_dashboard()` (sync) calls `asyncio.run()` for store queries (lines 261,
276), but it's called from inside `_run()` (async, line 367), which runs inside another
`asyncio.run()` (line 372). Nested `asyncio.run()` crashes with
`RuntimeError: asyncio.run() cannot be called from a running event loop`.

Same issue in `_poll_events()` (line 328) — it's async but calls `asyncio.run()`.

**Fix approach:**
- Make `_build_dashboard()` async — use `await store.list_agents()` and
  `await store.get_active_goal()` directly
- In `_poll_events()`, replace `asyncio.run(store.list_agents())` with
  `await store.list_agents()`
- The outer `_run()` orchestrates both `_poll_events()` and dashboard refresh as
  concurrent async tasks
- Keep the `Live` context manager — it works fine with periodic `live.update()` calls
  from an async loop

**Verify:** `hive init && hive start -b 5 -p coder` in one terminal, `hive watch` in
another. Dashboard should update without crashing.

---

## Task 2: Fix Mypy Errors

**Current:** 79 errors across 24 files. Most are annotation noise, but some are real.

**Priority fixes (real type-safety gaps):**
- `daemon/loop.py`: `WorldState | None` passed where non-optional `WorldState` expected
- `interactions/runner.py`: type mismatches with `GenerateResult` vs old return types
- Missing `types-PyYAML` stub — add to dev dependencies

**Lower priority (annotation noise):**
- Bare `dict` / `list` without type params throughout
- `Any` return types in world/stats.py, runtime/workflow.py, etc.

**Verify:** `uv run mypy src` — target zero `arg-type` and `union-attr` errors. The
`type-arg` noise can stay for now.

---

## Task 3: Update README Architecture Diagram

**File:** `README.md` line ~57

**Problem:** Shows `execution/` which was deleted. Should show `runtime/` instead.
Also missing entries for `context.py`, `checkpoint.py`, `world/`.

**Verify:** `ls src/hive/ | sort` matches the diagram.

---

## Task 4: Integration Test — End-to-End Daemon Loop

**Goal:** Prove the daemon loop actually works: spawn agent → existence loop generates
goal → suffering updates → events logged → state persisted.

**Approach:**
- Use `researcher` profile with a mocked model provider (don't call real LLMs)
- Short heartbeat (0.5s), run 3 cycles, then stop
- Assert: goal was generated, suffering state updated, events written to JSONL,
  agent state in SQLite
- Use temp directories for `.hive/` and `logs/`
- Existing test patterns in `tests/` — match the style

**File:** `tests/test_daemon_integration.py`

**Verify:** `uv run pytest tests/test_daemon_integration.py -v`
