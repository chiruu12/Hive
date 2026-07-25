# Stability 01: Daemon fail-closed policy (guards, budget, kill-switch)

**Status: implemented** (2026-07-22) — fail-closed guard registration, budget kill-switch wiring, life-event spend recording, tests and docs updated.

## Goal

Define and implement a consistent **fail-closed** policy for safety-critical daemon controls (phase guards, budget kill-switch) so exceptions and misconfiguration cannot silently disable spend limits or allow guarded phases to run.

## Why (stability)

Today, a broken `CostBudgetGuard` or `BudgetTracker` integration fails **open**: the daemon keeps spending. Combined with `budget_usd=0` / `budget_tokens=0` meaning unlimited (documented in `BudgetTracker.is_exceeded()` and `DaemonConfig`), operators can believe they have a kill-switch when they do not. Adversarial tests in `tests/adversarial/test_daemon_resilience.py` (`test_guard_exception_allows_by_default`) explicitly encode this as expected behavior.

For stability (not security theater), spend limits and operator pause controls must be **predictable**: either they block work, or config/docs say explicitly that they are off.

## Current state (files)

| Area | Location | Behavior today |
|------|----------|----------------|
| Guard exception handling | `src/hive/daemon/hooks.py` `HookRegistry.check_guards()` (lines 45–67) | Any guard exception → log + **allow phase** |
| Budget guard | `src/hive/daemon/gates.py` `CostBudgetGuard` | Blocks when `BudgetTracker.is_exceeded()`; `budget=None` → always allow; typed as `Any` |
| Budget tracker | `src/hive/daemon/budget.py` `BudgetTracker` | `0` = unlimited for USD and tokens; `on_exceeded` callback supported but **not wired** in daemon |
| Guard registration | `src/hive/daemon/loop.py` `HiveDaemon.__init__()` (lines 173–187) | `CostBudgetGuard` on `GOAL_PURSUIT` and `GOAL_GENERATION` only |
| Life-event LLM bypass | `src/hive/daemon/loop.py` `_process_life_events()` (lines 979–985) | Checks `is_exceeded()` at loop entry; no phase guard |
| Manual pause guard | `src/hive/daemon/gates.py` `ManualPauseGuard` | Implemented, **never registered** in `loop.py` |
| Config defaults | `src/hive/config.py` `DaemonConfig` (lines 135–137) | `budget_usd=0.0`, `budget_tokens=0` → unlimited |
| Tests | `tests/adversarial/test_daemon_resilience.py`, `tests/test_budget.py`, `tests/test_phase.py` | Fail-open guard test; zero-budget-unlimited test |

## Proposed changes (numbered)

1. **Document and codify guard failure policy** in `HookRegistry.check_guards()`:
   - Add optional per-guard or per-registration flag: `fail_closed: bool` (default `False` for third-party guards, `True` for built-in safety guards).
   - Built-in `CostBudgetGuard` registrations in `loop.py` use `fail_closed=True`.
   - On exception when `fail_closed=True`: log at ERROR, return `False` (block phase), emit a hook event e.g. `guard_failed` with guard name and phase.

2. **Harden `CostBudgetGuard`** in `src/hive/daemon/gates.py`:
   - Type `_budget` as `BudgetTracker | None` (not `Any`).
   - If `_budget` is `None`, log once at WARNING and treat as fail-closed for `GOAL_PURSUIT` / `GOAL_GENERATION` **or** require a tracker in daemon init (prefer: daemon always passes `self._budget`, guard never sees `None` in production).

3. **Make unlimited budget explicit in config** (`src/hive/config.py`, docs):
   - Keep `0` as unlimited for backward compatibility.
   - Add optional sentinel or doc-only convention: comment + CLI/`hive budget` output must say `"unlimited"` when both limits are 0 (already partially in `GET /budget` via `remaining`).
   - Optional follow-up (product): `budget_usd: null` vs `0` -- defer unless team wants breaking change.

4. **Wire `on_exceeded` kill-switch** in `HiveDaemon.__init__()`:
   - Pass callback that sets a daemon flag (e.g. `_budget_exceeded = True`) and logs once.
   - In `_run()` heartbeat, skip spawning new LLM work for agents when flag set (still allow cleanup, alarm marking, retention).
   - Ensures spend stops even if a guard check is skipped on a code path.

5. **Extend budget coverage to life events**:
   - After budget exceeded, `_process_life_events()` already returns early; add `await self._budget.record(...)` after successful `event_provider.generate()` (today life events spend tokens without updating tracker).
   - Register `CostBudgetGuard` on any future phase that calls the LLM outside `GOAL_PURSUIT` / `GOAL_GENERATION`, or centralize LLM spend recording.

6. **Update tests** to match new contract:
   - Change `test_guard_exception_allows_by_default` to test both modes (generic guard fail-open, `CostBudgetGuard` fail-closed).
   - Add integration-style test: mock provider + small `budget_usd`, run one daemon cycle, assert second cycle returns `"guarded"` or agents idle without LLM call.

7. **Clarify docs** (`docs/guide/daemon-mode.md`, `docs/getting-started/cli-quickstart.md`):
   - State that `0` = unlimited.
   - Distinguish per-agent pause (`AgentStatus.PAUSED` in store) from daemon-wide `ManualPauseGuard` (see plan 02).

## Non-goals

- Flipping `guardrails.enabled` default to `True` (product/security track).
- Flipping `approval.enabled` default to `True`.
- Replacing the six-phase cycle machine (plan 02 / 04).
- Adding default non-zero budget in config (production template only, optional doc).

## Risks / rollback

| Risk | Mitigation |
|------|------------|
| Fail-closed on guard bugs blocks all agent work | Feature flag via config `daemon.guards_fail_closed: bool` default `True`; rollback by setting `False` |
| Stricter behavior breaks tests assuming fail-open | Update adversarial + phase tests in same PR |
| `on_exceeded` callback stops daemon too aggressively | Callback only sets flag; heartbeat continues for housekeeping |

Rollback: revert `hooks.py` fail-closed branch and guard registration flags; keep explicit unlimited labeling in CLI/API.

## Acceptance criteria (testable)

```bash
uv run pytest tests/adversarial/test_daemon_resilience.py tests/test_budget.py tests/test_phase.py -v
uv run pytest tests/ -v --tb=short
```

- [x] `CostBudgetGuard` with a raising `should_proceed` implementation blocks phase entry (fail-closed).
- [x] Third-party guard without `fail_closed` still fails open (backward compatible for extensions).
- [x] `BudgetTracker(budget_usd=0)` still never exceeds; `hive budget` / `GET /budget` reports `"unlimited"` or equivalent when both limits are 0.
- [x] When `budget_usd=1.0` and spend recorded ≥ 1.0, next `GOAL_PURSUIT` / `GOAL_GENERATION` returns cycle result `"guarded"` (unit or thin daemon test).
- [x] `on_exceeded` fires once; daemon does not schedule new goal pursuit after exceed (integration test).
- [x] Life-event LLM calls increment `BudgetTracker.spent_tokens` / cost when estimatable.
- [x] No new mypy errors in `src/hive/daemon/gates.py`, `hooks.py`, `loop.py`.

## Suggested implementation order inside this plan

1. Add `fail_closed` to guard registration + `check_guards()` behavior.
2. Type and harden `CostBudgetGuard`; register with `fail_closed=True`.
3. Wire `on_exceeded` flag in `HiveDaemon`.
4. Record life-event spend in `_process_life_events()`.
5. Update tests and docs.
6. Optional: `daemon.guards_fail_closed` config escape hatch.

## Estimate

**M** (2–3 days) -- moderate behavior change, test and doc updates required.
