# Stability 05: Adversarial / resilience suite as merge gate

**Status: implemented** (2026-07-22) — CI `resilience` job, adversarial marker, FD fix, daemon integration regressions.

## Goal

Make `tests/adversarial/` a **required CI merge gate** with documented coverage, close known test gaps (misleading FD counting, missing daemon integration regressions), and give the team a single command to run before merge.

## Why (stability)

The adversarial suite (~170 tests) exercises abuse paths for shell, SSRF, budget guards, wake sources, and inter-agent sanitization. Today it runs only as part of the full pytest job in `.github/workflows/ci.yml` with no explicit gate — a regression in budget fail-closed or resource cleanup can slip through if reviewers focus on the coverage leg only.

Stability-01 landed fail-closed guards, `on_exceeded` kill-switch wiring, `GeneratedGoal` spend metering, and life-event budget recording. Those behaviors live primarily in `tests/test_budget.py` and `tests/test_phase.py`, **outside** the adversarial directory. Plan 05 moves the highest-value regressions into `tests/adversarial/` and wires CI so reverting stability-01 fails the merge gate.

## Current state (concrete files)

### CI (`.github/workflows/ci.yml`)

| Job | What runs | Gap |
|-----|-----------|-----|
| `lint` | ruff + mypy on 3.12 | OK |
| `test` | `uv run pytest tests/ -v` on 3.11–3.13 | Adversarial mixed in; no dedicated failure signal |
| `docs` / `build` | mkdocs + wheel | OK |

**No** separate adversarial job, marker filter, or `-x` fast-fail step.

### Adversarial inventory (`tests/adversarial/`)

| File | ~Tests | Focus |
|------|--------|-------|
| `test_daemon_resilience.py` | 15 | Budget unit stress, phase guards (fail-open vs fail-closed), hooks |
| `test_resource_exhaustion.py` | 11 | Wake cleanup, EventLog load, semantic memory, budget concurrency, **broken FD test on macOS** |
| `test_shell_sandbox.py` | ~80 parametrized | Shell escape / operator blocking |
| `test_ssrf_bypass.py` | 15 | URL safety / web toolkit |
| `test_approval_bypass.py` | 7 | HITL when enabled |
| `test_inter_agent_guardrails.py` | — | Comms/A2A sanitization |
| `test_sub_agent_privileges.py` | 12 | H3 allowlist |
| `test_orchestrator_workspace.py` | — | `set_workspace` containment |

### Stability-01 outcomes relevant to this plan

| Area | File(s) | Behavior (implemented) |
|------|---------|------------------------|
| Guard fail-closed | `src/hive/daemon/hooks.py`, `loop.py` | `CostBudgetGuard` registered with `fail_closed=daemon.guards_fail_closed` (default `True`) |
| Kill-switch | `src/hive/daemon/loop.py` | `on_exceeded` sets `_budget_exceeded`; heartbeat skips new LLM work |
| Goal generation metering | `loop.py`, `agents/existence.py`, `goal_strategy.py` | `GeneratedGoal.cost_usd` / `tokens` recorded before save |
| Life events | `loop.py` `_process_life_events()` | Early return when exceeded; spend recorded after LLM |
| Unit/integration tests | `tests/test_budget.py`, `tests/test_phase.py` | Guarded cycle, kill-switch, life-event tests — **not in adversarial/** |

### Known gaps (merge-gate scope)

| Gap | Evidence | Plan 05 action |
|-----|----------|----------------|
| No CI adversarial job | `ci.yml` | Dedicated `resilience` job on Ubuntu + Python 3.12 |
| Guard regressions outside adversarial | `test_budget.py` only | Copy thin daemon integration tests into `test_daemon_resilience.py` |
| macOS FD test is a no-op | `test_resource_exhaustion.py` `_count_open_fds()` returns `RLIMIT_NOFILE` on Darwin | Use `/proc/.../fd` on Linux; `lsof -p $PID` on macOS; **skip** if neither works |
| Concurrent agent cycle isolation | `loop.py` `asyncio.gather` + `_run_agent_cycle_guarded` | Adversarial test: one agent raises, sibling completes |
| Wake task leak under stress | Only 10-iteration test today | 100× create/cancel `CompositeWakeSource`; task delta bounded |
| Concurrent budget overshoot (PARTIAL) | Guard checked at phase entry; two agents can both pass `GOAL_GENERATION` before either records | Document + regression test bounding overshoot to ≤ one generation spend |
| No pytest `adversarial` marker | `pyproject.toml` | Register marker; auto-apply in `tests/adversarial/conftest.py` |

### Explicitly deferred (not plan 05)

| Item | Owner plan |
|------|------------|
| Toolkit factory / `set_workspace` deprecation | stability-03 |
| `ManualPauseGuard` vs `hive pause --all` | stability-02 |
| `loop.py` decomposition | stability-04 |
| Fixing concurrent overshoot in production (lock around check+record) | Future hardening PR — test documents current bound |

## Proposed changes (numbered)

1. **Register pytest marker** in `pyproject.toml`:
   ```toml
   [tool.pytest.ini_options]
   markers = [
       "adversarial: stability and abuse tests (required CI merge gate)",
   ]
   ```

2. **Auto-mark adversarial tests** — add `tests/adversarial/conftest.py`:
   ```python
   def pytest_collection_modifyitems(items: list) -> None:
       for item in items:
           item.add_marker(pytest.mark.adversarial)
   ```

3. **CI job `resilience`** in `.github/workflows/ci.yml` (Python 3.12, Ubuntu):
   ```yaml
   resilience:
     name: Adversarial / resilience gate
     runs-on: ubuntu-latest
     steps:
       - uses: actions/checkout@v4
       - uses: astral-sh/setup-uv@v4
       - uses: actions/setup-python@v5
         with:
           python-version: "3.12"
       - run: uv sync --extra api
       - name: Adversarial / resilience gate
         run: uv run pytest tests/adversarial/ -v --tb=short -x
   ```
   Runs in parallel with `test` matrix; does **not** duplicate coverage gating.

4. **Document merge checklist** — already in `docs/plans/stability-index.md`; add one line to `docs/guide/developer-guide.md` under development setup.

5. **Fix FD counting** in `tests/adversarial/test_resource_exhaustion.py`:
   - `_count_open_fds() -> int | None`: `/proc/pid/fd` on Linux; `lsof -p PID` line count on macOS.
   - Skip test with explicit reason when counting unavailable (never compare against `RLIMIT_NOFILE`).

6. **Add adversarial daemon integration tests** in `test_daemon_resilience.py`:

   | Test | Assert |
   |------|--------|
   | `test_concurrent_agent_cycles_isolate_failures` | `asyncio.gather` on `_run_agent_cycle_guarded`: failing agent → `None`, sibling → `"completed"` |
   | `test_exceeded_budget_blocks_agent_cycle` | Pre-seed spend ≥ cap → `_run_agent_cycle` returns `"guarded"`, `budget_exceeded` True |
   | `test_kill_switch_set_on_budget_exceed` | Record past cap via daemon tracker → `daemon.budget_exceeded is True` |
   | `test_concurrent_goal_generation_overshoot_bounded` | Two agents, custom strategy spending 0.06 each, budget 0.10 → total spend ≤ 0.12 (documents ≤1 generation overshoot) |

7. **Wake stress test** in `test_resource_exhaustion.py`:
   - 100× create/cancel `CompositeWakeSource`; `len(asyncio.all_tasks())` delta `< 10`.

8. **Align with stability-01 guard tests** (already done in adversarial file):
   - Keep `test_guard_exception_allows_by_default` (extension fail-open).
   - Keep `test_guard_exception_blocks_when_fail_closed` and `test_cost_budget_guard_fail_closed_on_exception`.

9. **Optional (document only):** pre-commit hook `pytest tests/adversarial/ -q` — non-blocking.

## Non-goals

- Running adversarial tests on every Python matrix leg (gate on 3.12 only).
- Fuzzing / Hypothesis infrastructure.
- Separate security-only CI workflow (same suite is sufficient).
- Implementing stability-02/03/04.
- Fixing concurrent budget race in production code (test documents bound only).
- Per-module coverage floor on adversarial job.

## Risks / rollback

| Risk | Mitigation |
|------|------------|
| CI time +~30–60s | Suite is ~170 tests; monitor; `-x` stops early on failure |
| Flaky concurrent tests | Deterministic mocks; no real LLM; short timeouts |
| `lsof` missing in CI | Linux uses `/proc`; macOS dev uses `lsof` (preinstalled on Darwin) |
| Overshoot test too strict | Bound set to 2× single-generation spend (documented PARTIAL gap) |

**Rollback:** Remove `resilience` job from `ci.yml`; tests remain in tree for local runs.

## Acceptance criteria (testable)

```bash
# Primary merge gate (local + CI)
uv run pytest tests/adversarial/ -v --tb=short

# Marker registration (no warnings)
uv run pytest tests/adversarial/ --strict-markers -q

# Validate CI workflow syntax (optional local)
# act -j resilience   # if act installed
```

Checklist:

- [x] CI workflow includes `resilience` job that fails PR on adversarial test failure.
- [x] All files under `tests/adversarial/` discoverable and passing on Linux (GitHub Actions).
- [x] Marker `adversarial` registered; auto-applied; `--strict-markers` passes.
- [x] `test_concurrent_agent_cycles_isolate_failures` passes.
- [x] `test_exceeded_budget_blocks_agent_cycle` passes (daemon integration in adversarial/).
- [x] `test_kill_switch_set_on_budget_exceed` passes.
- [x] `test_composite_wake_stress_no_task_leak` (100 iterations) passes.
- [x] `test_event_log_does_not_leak_fds` uses honest FD counting or skips with reason on unsupported platforms.
- [x] `docs/plans/stability-index.md` notes plan 05 refreshed + CI enforced.
- [x] `docs/guide/developer-guide.md` mentions adversarial merge gate command.

## Suggested implementation order

1. Add CI `resilience` job (immediate value if tests pass).
2. Register marker + `tests/adversarial/conftest.py`.
3. Fix `_count_open_fds()` + skip semantics.
4. Add concurrent cycle isolation test.
5. Add budget/kill-switch adversarial integration tests.
6. Add wake stress + concurrent overshoot bound test.
7. Update plan index + developer guide one-liner.

## Estimate

**S** (~1 day): CI + markers + FD fix + 4–5 new tests. Stability-01 guard realignment already landed in adversarial file; no extra day required.
