# Stabilization Phase 1 -- Restart and timeout continuity

## Problem statement

Phase C documented and implemented pursuit transcript resume **within a running daemon**, but **verified runtime behavior** abandons active goals and deletes transcripts on daemon restart and on cycle timeout. This contradicts `docs/plans/fix-phase-c-pursuit-continuity.md`, `docs/guide/daemon-mode.md`, and operator expectations for persistent agents.

### Exact files and functions

| Area | Location | Verified behavior |
|------|----------|-------------------|
| Resume on start | `src/hive/daemon/run_lifecycle.py` `RunLifecycle.resume_agents()` lines 188--192 | Calls `abandon_goal()` for every non-parked active goal |
| Shutdown | `RunLifecycle.shutdown()` lines 225--227 | Calls `abandon_goal()` after checkpoint |
| Goal abandon | `src/hive/memory/store.py` `abandon_goal()` | Deletes pursuit transcript rows |
| Cycle timeout | `src/hive/daemon/agent_cycle.py` `AgentCycleRunner.run_guarded()` lines 61--74 | Timeout logs "abandoning goal" and calls `abandon_goal()` |
| Pursuit transcript | `src/hive/memory/pursuit_transcript.py` | Populated during pursuit; wiped on abandon |
| Parked approval | `run_lifecycle.py` `resume_agents()` parked branch | **Correct:** preserves WAITING + active goal when approval pending |
| Tests (misleading) | `tests/test_auto_resume.py` `test_shutdown_abandons_active_goals` | Encodes abandon semantics -- must flip |

**Label:** All items above are **Verified defect** (multiple audits + code inspection).

## Scope

- Preserve active goals and pursuit transcripts across daemon stop/start under explicit config policy.
- On cycle timeout: park agent and **retain** goal + transcript (align with Phase B/C continue semantics).
- Maintain parked-approval behavior across restart (already correct).
- Add real stop/start integration tests with transcript assertions.
- Rollback flag for operators who relied on stale-goal cleanup.

## Non-goals

- Cross-agent goal transfer or manual goal editing APIs.
- Semantic summarization of long transcripts.
- Changing ReAct algorithm or profile `max_steps` wiring (Phase B done).
- Shutdown PID/budget ordering (Phase 2).

## Implementation slices

### Slice 1.1 -- Config policy

1. Add `daemon.preserve_active_goals_on_restart: bool = true` (default **preserve**).
2. Add `daemon.preserve_active_goals_on_timeout: bool = true`.
3. Document in `docs/guide/daemon-mode.md` and config tables.
4. When `false`, retain today's abandon-on-restart/timeout behavior for backward compatibility.

### Slice 1.2 -- `resume_agents()` continuity

1. When preserve flag true and not parked: **do not** call `abandon_goal()` for active goals.
2. Set agent to `IDLE` (or `ACTIVE` pursuit-ready) while keeping goal row status active.
3. Verify transcript rows still present via `pursuit_transcript.load_messages(goal_id)`.
4. Log `resumed_active_goal` telemetry event.

### Slice 1.3 -- `shutdown()` continuity

1. Checkpoint agents with active goal metadata intact.
2. When preserve flag true: skip `abandon_goal()` on shutdown (still write checkpoint).
3. Ensure transcript not deleted on graceful shutdown.

### Slice 1.4 -- Timeout park semantics

1. In `AgentCycleRunner.run_guarded()` `TimeoutError` handler: replace abandon with:
   - Persist partial pursuit transcript (already flushed per cycle if Phase C wired).
   - `update_agent_status(IDLE)` -- ready for next heartbeat.
   - Leave goal active in store.
2. Record timeout spend via existing Phase D paths before parking.

### Slice 1.5 -- Integration tests

1. New `tests/test_restart_continuity.py`:
   - Start daemon, agent receives goal, partial pursuit (mock LLM 2 steps).
   - Stop daemon (`RunLifecycle.shutdown()`), start new daemon instance same hive dir.
   - Assert active goal id unchanged, transcript message count monotonic, second pursuit resumes context.
2. Update `tests/test_auto_resume.py`: flip `test_shutdown_abandons_active_goals` to opt-in legacy flag test.
3. Extend `tests/test_daemon_timeout.py`: timeout does **not** delete transcript when preserve flag true.

## Acceptance criteria

```bash
uv run pytest tests/test_restart_continuity.py tests/test_auto_resume.py tests/test_daemon_timeout.py tests/test_pursuit_transcript.py -v
uv run pytest tests/test_daemon_integration.py -v -k restart
```

- [x] Real stop/start: active goal survives; transcript length >= pre-shutdown count.
- [x] Parked approval: still WAITING with pending approval after restart (regression).
- [x] Timeout: goal remains active; transcript preserved; agent IDLE for next cycle.
- [x] `preserve_active_goals_on_restart=false`: legacy abandon behavior with explicit test.
- [x] Docs updated: pursuit diagram shows restart resume path.

**Status:** VERIFIED (2026-07-25)

## Regression matrix (Hardening A--G)

| Phase | Check |
|-------|-------|
| B | Zombie goal / max_steps continue still works with preserved goals |
| C | Transcript append/load unchanged; only abandon triggers removed |
| D | Timeout records spend without abandon |
| E | Recall on pursuit still sees transcript-backed context |
| F | No change to comms sanitization |
| G | New keys appear in config reload matrix as restart-required |

## Rollback / compatibility

- Config flags default to **preserve** (correct framework semantics).
- Set both flags `false` to restore pre-stabilization abandon behavior.
- No SQLite migration required if goal/transcript schema unchanged.

## Dependencies

- **Phase 0** -- deterministic test suite green before behavior change.
- **Soft:** Phase 2 shutdown ordering should land soon after to avoid checkpoint/PID races during restart tests.

## Risks and YAGNI cuts

| Risk | Mitigation |
|------|------------|
| Stale goals after crash | Optional max goal age config -- **YAGNI** unless operator request |
| Duplicate pursuit after restart | Idempotent transcript load in `DaemonAgentAdapter.pursue_goal` |
| Tests assumed abandon | Update `test_auto_resume` explicitly |

**YAGNI:** Automatic goal staleness sweep on restart; document manual `hive goals abandon` instead.

## Finding labels

| Finding | Label |
|---------|-------|
| Restart abandons active goals + deletes transcripts | **Verified defect** |
| Timeout abandons + deletes transcripts | **Verified defect** |
| Parked approval preserved on restart | Correct behavior (regression anchor) |
| Phase C docs imply restart resume | **Verified defect** (docs/code gap) |
