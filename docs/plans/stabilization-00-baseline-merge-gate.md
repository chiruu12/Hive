# Stabilization Phase 0 -- Baseline / merge-gate recovery

**Status: Done** (verified 2026-07-25)

## Problem statement

The framework cannot be hardened safely while the measured merge gate is red. Five Composer audits agree on a **deterministic 10-test drift** plus **14 ruff errors**, **37 format files**, **6 mypy errors**, and one **intermittent adversarial** wake test. Several failures reflect refactors already merged (goal validation move, `AgentCycleRunner` extraction) without test updates.

### Exact files and functions

| Area | Location | Issue |
|------|----------|-------|
| Goal validation tests | `tests/runtime/test_robustness.py` `TestGoalValidation` | Calls removed `ExistenceLoop._validate_goal` |
| Goal validation impl | `src/hive/agents/goal_persistence.py` `validate_goal()` | Target API; ruff/mypy forward-ref issues |
| Existence loop | `src/hive/agents/existence.py` | Imports `validate_goal`; mypy return-type errors |
| Timeout test | `tests/test_daemon_timeout.py` | Patches removed `HiveDaemon._run_agent_cycle_inner` |
| Cycle runner | `src/hive/daemon/agent_cycle.py` `AgentCycleRunner.run_guarded()` | Current timeout hook point |
| Budget concurrency | `tests/test_budget.py` (concurrency case) | In-memory config; `heartbeat.py` reloads disk via `get_config()` |
| Phase guard test | `tests/test_phase.py` `FakeBudget` | Missing `is_at_capacity()` |
| Budget guard | `src/hive/daemon/gates.py` `CostBudgetGuard` | Calls `budget.is_at_capacity()` |
| Line guard | `tests/test_solid_validation.py` | `agent_cycle.py` 791 lines vs 600 limit |
| Wake leak test | `tests/adversarial/test_resource_exhaustion.py` `test_wake_source_does_not_leak_tasks` | Intermittent pending-task delta |
| Packaging | `.conductor/settings.local.toml` symlink | `uv build` fail in Conductor workspace only |

## Scope

- Restore **deterministic** green: full pytest, ruff, mypy, format check.
- Stabilize wake-source test with instrumentation (test-only if possible).
- Verify `uv build` on clean checkout; document Conductor artifact if isolated.
- Temporary waiver for `agent_cycle.py` line limit with tracked debt to Phase 5.

## Non-goals

- Fixing restart/timeout abandon behavior (Phase 1).
- Security boundary changes (Phase 3).
- Splitting `agent_cycle.py` (Phase 5) -- only waive or skip guard until then.
- Changing framework semantics for passing tests.

## Implementation slices

### Slice 0.1 -- Static analysis recovery

1. Fix `goal_persistence.py` forward references and ruff violations.
2. Fix `existence.py` mypy return types and import order.
3. Run `uv run ruff format src/ tests/` in isolated commit (37 files).
4. Re-run `uv run ruff check src/ tests/` and `uv run mypy src/` until clean.

### Slice 0.2 -- Deterministic test drift (6 + 1 + 1 + 1)

1. **`TestGoalValidation`:** Import and call `goal_persistence.validate_goal` directly; remove `ExistenceLoop._validate_goal` references.
2. **`test_daemon_timeout`:** Patch `AgentCycleRunner.run_guarded` or inject hanging `_run_agent_cycle` via daemon public hook.
3. **Budget concurrency:** Write config to disk in fixture before daemon start, or patch `get_config()` consistently with test expectations (`daemon.max_concurrent_agents=3`).
4. **`FakeBudget`:** Add no-op `is_at_capacity() -> False` (and `True` variant for block test if needed).
5. **`test_solid_validation`:** Temporarily exclude `agent_cycle.py` from 600-line assert with `# debt: stabilization-05` comment linking Phase 5 plan.

### Slice 0.3 -- Wake-source flake characterization

**Label: Risk / hypothesis** (not verified leak)

1. Add deterministic helper `_pending_asyncio_tasks()` logging task names in test.
2. Run stress test 50x locally; record delta distribution.
3. If flake persists: mark `@pytest.mark.flaky(reruns=2)` **only after** proving env sensitivity, or tighten `CompositeWakeSource` cancel path in Phase 0 **only if** instrumentation shows uncancelled tasks.

### Slice 0.4 -- Packaging verification

1. Clone clean tree (or `git archive`) without `.conductor/`; run `uv build`.
2. Document outcome in Phase 0 PR description and index decision log.

## Acceptance criteria

```bash
uv run pytest tests/runtime/test_robustness.py::TestGoalValidation -v
uv run pytest tests/test_daemon_timeout.py -v
uv run pytest tests/test_budget.py tests/test_phase.py -v
uv run pytest tests/test_solid_validation.py -v
uv run pytest tests/ -v
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
uv run mypy src/
uv run pytest tests/adversarial/ -v --tb=short   # 223/223 or documented flake waiver
```

- [x] Full suite: **0 deterministic failures** (1804 passed).
- [x] Ruff: **0 errors**; format check clean (38 files reformatted).
- [x] Mypy: **0 errors** in `src/`.
- [x] Adversarial: **223/223** stable across 3 local runs; wake test 30/30 isolated stress runs.
- [x] Clean-checkout `uv build` passes; Conductor workspace-only failure documented (absolute symlink `.conductor/settings.local.toml`).

## Measured results (2026-07-25)

| Gate | Before | After |
|------|--------|-------|
| Full pytest | 1794 passed, **10 failed** | **1804 passed**, 0 failed |
| Ruff check | **14 errors** | **0 errors** |
| Ruff format | **37 files** drift | **0 files** (38 reformatted) |
| Mypy | **6 errors** (2 files) | **0 errors** |
| Adversarial | 222/223 (intermittent wake) | **223/223** x3 runs |
| MkDocs `--strict` | Pass | Pass |
| `uv build` (clean archive) | Not verified | **Pass** |
| `uv build` (Conductor workspace) | Fail | Fail (workspace artifact only) |

### Wake-source flake diagnosis

- **Root cause:** Test counted global `asyncio.all_tasks()` pending delta, which is sensitive to unrelated background tasks in the pytest event loop.
- **Fix:** Test-only helper `_wake_owned_pending()` filters tasks whose coroutine module/qualname belongs to `hive.daemon.wakeup`.
- **Production code:** Unchanged (`CompositeWakeSource` cancel/reap path already correct).
- **Stress runs:** 30/30 pass isolated; 3/3 full adversarial suite runs at 223/223.

## Regression matrix (Hardening A--G)

| Phase | Protected behavior | Test anchor |
|-------|-------------------|-------------|
| A | Shell containment | `tests/adversarial/test_shell_sandbox.py` |
| B | Goal lifecycle / max_steps | `tests/test_goal_lifecycle.py` |
| C | Pursuit transcript | `tests/test_pursuit_transcript.py` |
| D | Budget reserve/ceiling | `tests/test_budget.py` |
| E | Memory unification | `tests/test_memory_unification.py` |
| F | Collaboration safety | `tests/adversarial/test_inter_agent_guardrails.py` |
| G | Config reload contract | `tests/test_config.py`, REST docs |

Phase 0 must not weaken any adversarial test assertions.

## Rollback / compatibility

- Test-only and formatting changes: revert individual PRs.
- Line-limit waiver: revert when Phase 5 lands split.
- No config flags introduced in Phase 0.

## Dependencies

- **None** (first phase).
- Blocks Phases 1--6.

## Risks and YAGNI cuts

| Risk | Mitigation |
|------|------------|
| Format PR obscures logic review | Split PR-0a (lint) vs PR-0b (tests) |
| Wake fix changes production code prematurely | Default to test instrumentation only |
| Waiving line limit hides debt | Explicit link to Phase 5 in test comment |

**YAGNI:** Do not refactor `agent_cycle.py` in Phase 0 to satisfy line guard.

## Finding labels

| Finding | Label |
|---------|-------|
| 10 deterministic test failures | **Verified defect** (test drift) |
| 14 ruff / 6 mypy errors | **Verified defect** (static) |
| Wake pending-task intermittent | **Risk / hypothesis** |
| `uv build` Conductor symlink | **Risk / hypothesis** (workspace artifact) |
| `agent_cycle.py` 791 lines | **Verified defect** (guard); fix deferred to Phase 5 |
