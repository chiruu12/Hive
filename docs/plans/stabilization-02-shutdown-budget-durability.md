# Stabilization Phase 2 -- Shutdown and budget durability

## Problem statement

Daemon shutdown and startup paths have **ordering and signaling gaps** that risk overlapping processes, lost budget state, and silent operator confusion. Economy life events may bypass reservation semantics established in Phase D.

### Exact files and functions

| Area | Location | Issue | Label |
|------|----------|-------|-------|
| PID release order | `run_lifecycle.py` `shutdown()` lines 196--198 | Unlinks `daemon.pid` **before** checkpoints | **Verified defect** |
| Budget flush | `src/hive/daemon/budget.py`, `loop.py` shutdown path | No guaranteed final `persist()` / flush on shutdown | **Verified defect** |
| Duplicate start | `run_lifecycle.py` `start()` lines 38--48 | Logs error and **returns silently** when live PID exists | **Verified defect** |
| Life events | `src/hive/daemon/economy_hooks.py` `process_life_events()` | Uses `budget.record()` not reserve/commit | **Risk / hypothesis** -- verify then close |
| Budget persist | `src/hive/daemon/budget.py` `BudgetTracker` | Phase D persist hooks | Depends on flush call site |

## Scope

- Reorder shutdown: checkpoints + budget flush **before** PID unlink.
- Final budget persist on graceful shutdown and SIGTERM path.
- Duplicate live daemon start raises explicit error or non-zero exit (CLI + embedded).
- Verify economy life-event spend uses reservation when `budget_mode=reserve`; fix if confirmed.
- Integration tests for stop/start budget continuity.

## Non-goals

- Full distributed locking beyond PID file.
- Changing budget reservation algorithm (Phase D done).
- Restart goal continuity (Phase 1).
- New economy features.

## Implementation slices

### Slice 2.1 -- Shutdown ordering

1. Move `lockfile.unlink()` to **end** of `shutdown()` after checkpoint loop succeeds (or best-effort with timeout).
2. Wrap checkpoint loop in try/finally: PID released only in `finally` after budget flush attempt.
3. Add structured log: `shutdown_phase=checkpoint|budget|pid_release`.

### Slice 2.2 -- Final budget flush

1. Call `BudgetTracker.persist()` (or equivalent) in `shutdown()` before PID release.
2. Ensure `HiveDaemon._shutdown()` delegate invokes flush even when economy disabled.
3. Test: spend during last cycle, shutdown, new daemon reads same spent totals from disk.

### Slice 2.3 -- Duplicate start signaling

1. When live PID detected in `start()`: raise `DaemonAlreadyRunningError` (new) or return `False` with documented contract.
2. CLI `hive start` / `hive daemon start`: print error to stderr, exit code **1**.
3. MCP `start_daemon` tool: return explicit message (already partial -- align wording).
4. REST embedded daemon: surface 409 if applicable.

### Slice 2.4 -- Life-event reservation audit

**Label: Risk / hypothesis** until confirmed

1. Trace `economy_hooks.process_life_events()` LLM calls through budget API.
2. If only `record()` used: wrap generation in `reserve()` / `commit()` or `record()` after failed reserve block.
3. Add adversarial test: life event cannot exceed ceiling under concurrent agents (bound documented).

### Slice 2.5 -- Tests

1. `tests/test_shutdown_durability.py`: PID exists during checkpoint; gone after complete shutdown.
2. Budget persist round-trip across daemon restart.
3. Duplicate start exits non-zero / raises.

## Acceptance criteria

```bash
uv run pytest tests/test_shutdown_durability.py tests/test_daemon_lifecycle.py tests/test_budget.py -v
uv run pytest tests/adversarial/test_daemon_resilience.py -v -k budget
```

- [x] Checkpoint files written before PID file removed (instrumented test).
- [x] Budget spent USD/tokens identical after stop/start within epsilon.
- [x] Second concurrent start fails loudly with actionable message.
- [x] Life-event audit documented in PR; fix merged if reserve gap confirmed.

**Status:** VERIFIED (2026-07-25)

## Regression matrix (Hardening A--G)

| Phase | Check |
|-------|-------|
| D | Reservation hard ceiling still blocks pursuit when exceeded |
| A--G | No change to shell, goals, transcripts, comms |
| stability-01 | Kill-switch on exceed still skips heartbeat work |

## Rollback / compatibility

- Shutdown ordering is strictly safer; no flag needed.
- Duplicate-start error may break scripts that ignored silent return -- document in CHANGELOG.
- Life-event fix behind existing `budget_mode` only.

## Dependencies

- **Phase 0** -- test infrastructure green.
- **Soft Phase 1** -- restart tests may share fixtures; ordering independent.

## Risks and YAGNI cuts

| Risk | Mitigation |
|------|------------|
| Shutdown hang if checkpoint slow | Per-agent timeout; still release PID in `finally` with warning |
| Scripts parsed silent duplicate start | CHANGELOG + exit code 1 |

**YAGNI:** File locking beyond PID; cross-platform flock deferred.

## Finding labels

| Finding | Label |
|---------|-------|
| PID unlinked before checkpoints | **Verified defect** |
| No final budget flush on shutdown | **Verified defect** |
| Duplicate start silent return | **Verified defect** |
| Life events use record not reserve | **Risk / hypothesis** |
