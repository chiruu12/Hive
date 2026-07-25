# Phase B -- Goal lifecycle correctness

**Status: Done**

## Goal

Make daemon goal pursuit **honest**: honor profile limits, handle `MAX_STEPS` explicitly, eliminate zombie active goals, unify custom `GoalStrategy` persistence with `ExistenceLoop`, and wire easy profile knobs (temperature, per-agent cost cap).

## Why (problems addressed -- bullet list with severity)

- **P0:** Profile `max_steps` ignored -- `AgentCycleRunner` builds `Agent(...)` without `max_steps=profile.max_steps`; `DaemonAgentAdapter.pursue_goal()` creates `Task(instruction=...)` with default 25 (`src/hive/daemon/agent_cycle.py`, `src/hive/runtime/bridge.py`).
- **P0:** `MAX_STEPS` zombie goals -- `DaemonAgentAdapter` maps only `FAILED` to `steps_failed=1`; `MAX_STEPS` yields `success=False` with `steps_failed=0`, so neither complete nor abandon branch runs (`agent_cycle.py` lines 313--411).
- **P0:** Active goal + `AgentStatus.IDLE` after partial pursuit -- agent forgets progress next heartbeat (feeds Phase C).
- **P1:** Custom `GoalStrategy` skips validation -- `agent_cycle.py` saves goal directly without `ExistenceLoop._validate_goal()` / duplicate-active check.
- **P1:** `ExistenceLoop` vs `GoalStrategy` save divergence -- existence saves inside `generate_goal()`; strategy path saves in `agent_cycle.py` with different hooks/events.
- **P2:** `temperature`, `max_cost_usd`, `max_tokens` from `AgentProfile` not passed to runtime `Agent` or provider (`src/hive/agents/profile.py`, `agent_context.py` provider cache).
- **P2:** `assess_conditions` bias -- only runs after pursuit with `outcome.steps_done`; MAX_STEPS / idle paths skew suffering stats.

## Related issues bundled

| ID | Finding |
|----|---------|
| LOOP-GOAL-01 | Profile `max_steps` not wired |
| LOOP-GOAL-02 | `MAX_STEPS` / zombie active goals |
| LOOP-GOAL-03 | `GoalStrategy` bypasses validation |
| LOOP-GOAL-04 | Temperature / per-agent budget not wired |
| LOOP-GOAL-05 | `GeneratedGoal` metering only on generation path (partial) |

## Current state (files)

| Area | Location | Behavior today |
|------|----------|----------------|
| Pursuit entry | `src/hive/daemon/agent_cycle.py` | New `Agent` per cycle; no profile step limit |
| Bridge | `src/hive/runtime/bridge.py` | `Task(instruction=...)` only |
| Runtime loop | `src/hive/runtime/agent.py` | `max_steps = task.max_steps or self._max_steps`; returns `TaskStatus.MAX_STEPS` |
| Outcome mapping | `bridge.py` | `success = status == COMPLETED` only |
| Goal generation | `src/hive/agents/existence.py` | Validates + saves goal; returns `GeneratedGoal` with spend |
| Custom strategy | `src/hive/agents/goal_strategy.py` | Protocol only; caller saves raw string |
| Profile | `src/hive/agents/profile.py` | `max_steps=20`, `temperature`, `max_cost_usd` defined |
| Telemetry | `src/hive/logging/trace.py`, `GoalLog` | Events for completed/abandoned; gap for max_steps / parked |

## Proposed changes (numbered)

1. **Wire profile limits into pursuit:**
   - Pass `max_steps=profile.max_steps`, `temperature=profile.temperature`, and `max_cost_usd=profile.max_cost_usd` (if `Agent` supports) when constructing runtime `Agent` in `agent_cycle.py`.
   - Pass `max_steps` into `Task(...)` in `DaemonAgentAdapter.pursue_goal()` (or set on `Agent` ctor consistently).

2. **Define explicit `MAX_STEPS` policy** (document in `docs/guide/daemon-mode.md`):
   - **Recommended default:** treat `MAX_STEPS` as *continuable* -- keep goal `active`, set status `IDLE`, emit `goal_progress` / `max_steps_reached` telemetry; Phase C adds transcript resume.
   - **Alternative (config flag):** `daemon.max_steps_policy: abandon | continue` for operators who prefer auto-abandon.
   - Map `TaskStatus.MAX_STEPS` in `bridge.py` to a distinct `GoalOutcome` flag (e.g. `hit_step_limit: bool`).

3. **Fix zombie / fall-through handling in `agent_cycle.py`:**
   - After pursuit, if not success / waiting_approval / abandoned, branch on `hit_step_limit` or explicit `outcome.status`.
   - Never leave `active` goal with unlogged indeterminate outcome.

4. **Unify goal persistence:**
   - Extract shared `save_generated_goal(agent_id, objective, *, validate=True)` used by `ExistenceLoop` and `GoalStrategy` paths.
   - Apply `_validate_goal()` for custom strategies unless `GoalContext.skip_validation` opt-in for trusted plugins.
   - Emit consistent `GoalLog` + `goal_generated` hook in one place.

5. **Provider temperature:** Ensure `create_runtime_provider` / cached provider calls pass profile temperature in `generate_with_metadata` (audit `src/hive/daemon/loop.py`, model providers).

6. **Telemetry:**
   - Add `GoalLog` event `max_steps` or extend `event` enum in logs.
   - Update `tests/test_narrative_in_prompt.py` / add `tests/test_goal_lifecycle.py` for wiring assertions.

## Non-goals

- Cross-heartbeat transcript (Phase C).
- Changing default profile `max_steps` value (20 vs 25 mismatch with runtime default -- document only).
- Rewriting `ExistenceLoop` prompt strategy.

## Risks / rollback

| Risk | Mitigation |
|------|------------|
| Continue policy increases LLM spend on stuck goals | Pair with profile `max_steps` + Phase D budget; optional cap on continuations per goal |
| Stricter validation breaks custom strategies | `skip_validation` flag on `GoalStrategy` registration |
| Abandon policy loses work | Default to continue; abandon opt-in |

Rollback: revert bridge outcome mapping; feature-flag `max_steps_policy`.

## Acceptance criteria (testable)

```bash
uv run pytest tests/test_goal_lifecycle.py tests/test_narrative_in_prompt.py tests/agents/test_existence.py -v
uv run pytest tests/test_daemon_integration.py -v -k goal
```

- [x] Agent with profile `max_steps: 3` stops pursuit at 3 tool/model steps (mock provider counts steps).
- [x] `TaskStatus.MAX_STEPS` no longer leaves goal active with no recorded outcome (per chosen policy).
- [x] Custom `GoalStrategy` that returns duplicate/rejected goal does not create store row when validation enabled.
- [x] `Agent` constructed in daemon uses profile `temperature` in provider call (mock asserts kwargs).
- [x] `docs/guide/prompt-assembly.md` and `docs/guide/daemon-mode.md` state max_steps + MAX_STEPS policy.

## Suggested implementation order

1. Failing tests for max_steps wiring + MAX_STEPS outcome.
2. Bridge + agent_cycle outcome branches.
3. Shared goal save/validate helper.
4. Temperature / max_cost_usd wiring.
5. Docs + telemetry.

## Estimate

**M** (2--3 days).

## Dependencies (prior phases)

None (start in parallel with Phase A). **Blocks** Phase C (policy must exist before resume) and Phase D (spend on all outcomes).
