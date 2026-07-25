# Phase D -- Budget hard ceiling

**Status: Done**

## Goal

Make daemon budget a **hard ceiling** under concurrency: eliminate material overshoot, record spend on timeout/cancel paths, optionally persist totals across restarts, and clarify the `budget_usd=0` unlimited footgun.

## Why (problems addressed -- bullet list with severity)

- **P0:** Concurrent budget overshoot -- `CostBudgetGuard` checked at phase entry; N concurrent agents can each pass before any `record()` (`tests/adversarial/test_daemon_resilience.py::test_concurrent_goal_generation_overshoot_bounded` documents PARTIAL gap).
- **P0:** Cycle timeout drops spend -- `AgentCycleRunner.run_guarded()` abandons goal on timeout without reading partial `GoalOutcome` / provider cost (`src/hive/daemon/agent_cycle.py` lines 56--78).
- **P1:** Budget not persisted -- `BudgetTracker` in-memory only (`src/hive/daemon/budget.py`); restart resets spend.
- **P1:** `budget_usd=0` means unlimited -- operators misconfigure kill-switch (`src/hive/config.py` `DaemonConfig`, stability-01 documented but footgun remains).
- **P2:** `GeneratedGoal` soft metering -- generation spend recorded after LLM call; race window before `record()` (`agent_cycle.py` lines 501--505).

## Related issues bundled

| ID | Finding |
|----|---------|
| REL-BUDGET-01 | Concurrent overshoot ≤ N × generation cost |
| REL-BUDGET-02 | Timeout path skips `_budget.record()` |
| REL-BUDGET-03 | No durable budget ledger |
| REL-BUDGET-04 | Zero budget = unlimited semantics |
| REL-BUDGET-05 | Post-call record race |

## Current state (files)

| Area | Location | Behavior today |
|------|----------|----------------|
| Tracker | `src/hive/daemon/budget.py` | Async lock on `record()`; `0` = unlimited |
| Guard | `src/hive/daemon/gates.py` `CostBudgetGuard` | Phase entry check |
| Kill-switch | `src/hive/daemon/loop.py` | `_budget_exceeded` flag (stability-01) |
| Recording | `src/hive/daemon/agent_cycle.py` | After pursuit/generation completes |
| Tests | `tests/adversarial/test_daemon_resilience.py` | Bounded overshoot test (xfail/document) |
| REST | `src/hive/server/routes/system.py` | `GET /budget` |

## Proposed changes (numbered)

1. **Reservation model (preferred):**
   - Add `BudgetTracker.reserve(estimate_usd, estimate_tokens) -> Reservation | None` before LLM call; commit actual on completion; release on failure.
   - Estimates: configurable defaults per phase (`daemon.budget_reserve_usd_generation`, `daemon.budget_reserve_usd_pursuit`) or last-moving-average.
   - Guard checks `available = budget - spent - reserved`.

2. **Serialize spend-critical sections (fallback if reservation too heavy):**
   - Global asyncio lock around goal generation + pursuit LLM invocations only (not whole cycle).

3. **Timeout / cancel spend:**
   - On `asyncio.wait_for` timeout, capture partial cost from provider/adapter if available; always `record()` best-effort.
   - Revisit timeout --> `abandon_goal` policy (coordinate Phase B/C): budget fix should not lose spend even if goal continues.

4. **Persist budget (optional, config-gated):**
   - Store `spent_usd`, `spent_tokens` in `.hive/budget.json` or SQLite row; load on daemon start.
   - `hive budget reset` CLI + `POST /budget/reset`.

5. **Operator clarity for zero = unlimited:**
   - `hive daemon` / `GET /budget` must print `"unlimited (budget_usd=0)"` prominently.
   - Optional validation warning in `hive config validate` when both limits zero and `daemon.warn_unlimited_budget: true` (default true in docs template only).

6. **Tests:**
   - Replace/document `test_concurrent_goal_generation_overshoot_bounded` with strict ceiling test under reservation.
   - Add timeout spend test with mock provider returning partial usage.

## Non-goals

- Per-agent budget caps (profile `max_cost_usd` is Phase B runtime concern).
- Billing integration / invoices.
- Changing fail-closed guard policy (stability-01 done).

## Risks / rollback

| Risk | Mitigation |
|------|------------|
| Over-reservation stalls agents | Conservative estimates + release on all exit paths |
| Persist file corruption | Atomic write; rebuild from logs optional |
| Stricter budget breaks dev workflows | Document `budget_usd: 0`; template uses non-zero in production example |

Rollback: `daemon.budget_mode: record_only` disables reservation.

## Acceptance criteria (testable)

```bash
uv run pytest tests/adversarial/test_daemon_resilience.py tests/test_budget.py -v
```

- [x] With `budget_usd=0.10` and 4 concurrent agents, total `spent_usd` ≤ `0.10 + epsilon` (epsilon documented as estimate slack only).
- [x] Cycle timeout after mock LLM call still increments `spent_usd` / `spent_tokens`.
- [x] `GET /budget` shows `unlimited` when limits are zero.
- [x] Optional: restart daemon preserves spend when persistence enabled.

## Suggested implementation order

1. Reservation API + unit tests in `tests/test_budget.py`.
2. Wire pursuit + generation in `agent_cycle.py`.
3. Timeout partial record.
4. Persistence + CLI (optional sub-PR).
5. Adversarial strict test + docs (`docs/guide/daemon-mode.md`, `docs/getting-started/cli-quickstart.md`).

## Estimate

**M** (2--4 days; +1 day if persistence included).

## Dependencies (prior phases)

- **Phase B** -- pursuit/generation exit paths must report cost consistently before reservation commit logic.
