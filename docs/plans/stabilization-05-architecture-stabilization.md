# Stabilization Phase 5 -- Architecture stabilization

## Problem statement

Structural debt blocks the merge gate and creates divergent secure assembly paths. `agent_cycle.py` exceeds the stability line guard immediately. REST one-shot and daemon toolkit assembly diverge, leaving `CommsToolkit` without guardrail injection.

### Exact files and functions

| Area | Location | Issue | Label |
|------|----------|-------|-------|
| Cycle module size | `src/hive/daemon/agent_cycle.py` (791 lines) | Fails `tests/test_solid_validation.py` 600-line guard | **Verified defect** |
| Line guard | `tests/test_solid_validation.py` | Enforced for extracted daemon modules | Policy |
| REST toolkit set | `src/hive/server/runner.py`, one-shot routes | Smaller intentional set | **By design** |
| Comms guardrails | `src/hive/tools/comms/toolkit.py` | No guardrail injection in REST path | **Verified defect** |
| Toolkit factory | `src/hive/daemon/toolkit_factory.py` | Daemon assembly | Reference implementation |
| Large files (optional) | `memory/store.py`, `runtime/agent.py`, `cli/main.py` | Size only | **Backlog** -- optional decomposition |

## Scope

- Split `agent_cycle.py` behavior-preservingly into submodules under 600 lines each.
- Add characterization tests before/after split (same phase outcomes, transcript hooks).
- Introduce **shared secure-minimal toolkit factory** for REST one-shot + documented daemon subset -- **not** full dangerous parity.
- Inject guardrails into `CommsToolkit` on all assembly paths.

## Non-goals

- Splitting `HiveStore`, `runtime/agent.py`, or `cli/main.py` (explicitly optional backlog).
- Changing ReAct loop algorithm.
- Full REST == daemon toolkit list.
- Per-phase module extraction beyond cycle runner (stability-04 optional later).

## Implementation slices

### Slice 5.1 -- Characterization tests (pre-split)

1. Capture golden tests for one full agent cycle: phase order, guard calls, transcript persist points, timeout branch.
2. Mock store + provider; assert hook call sequence.
3. Must pass on main before any move.

### Slice 5.2 -- `agent_cycle.py` decomposition

Follow [stability-04-loop-decomposition.md](stability-04-loop-decomposition.md) spirit but split **within** cycle module first:

| New module | Responsibility |
|------------|----------------|
| `agent_cycle_runner.py` | `AgentCycleRunner` class shell, `run_guarded` |
| `agent_cycle_phases.py` | Phase bodies (_goal_generation, _pursuit, etc.) |
| `agent_cycle_outcomes.py` | Goal outcome handling, abandon/complete helpers |

1. Mechanical move only; no semantic edits in same PR.
2. Re-enable 600-line guard for all daemon modules.
3. `HiveDaemon` imports unchanged public surface.

### Slice 5.3 -- Secure-minimal REST factory

1. New `src/hive/daemon/secure_toolkit_factory.py` (or extend `toolkit_factory.py`):
   - `build_minimal(guardrails, workspace, agent_id)` returns agreed REST subset.
   - Always injects guardrails into comms, shell (if present), web, sub_agents.
2. Wire `server/runner.py` to factory; remove duplicate manual lists.
3. Document intentional omissions vs daemon (orchestrator, shell, etc.) in `docs/guide/rest-api.md`.

### Slice 5.4 -- CommsToolkit guardrail injection

1. Add optional `GuardrailRegistry` ctor param to `CommsToolkit`.
2. Daemon and REST factories pass registry.
3. Adversarial comms tests pass on both paths.

### Slice 5.5 -- Optional backlog note (no implementation)

Document-only section in index for future splits:

- `HiveStore` (>1600 line guard): extract recall/migration only when needed.
- `runtime/agent.py`: extract tool loop vs provider adapter when touch count high.
- `cli/main.py`: typer subapp modules by command group.

## Acceptance criteria

```bash
uv run pytest tests/test_solid_validation.py -v
uv run pytest tests/test_daemon_integration.py tests/test_phase.py -v
uv run pytest tests/test_toolkit_factory.py tests/test_api_production.py -v
uv run pytest tests/adversarial/test_inter_agent_guardrails.py -v
```

- [x] All `daemon/*.py` modules < 600 lines.
- [x] Characterization tests pass before and after split (same assertions).
- [x] REST one-shot uses shared minimal factory; comms guardrails active.
- [x] No new circular imports (mypy clean).

**Status:** VERIFIED (2026-07-25) — agent_cycle split into runner/phases/outcomes; secure_toolkit_factory wired on REST path; line guard re-enabled.

## Regression matrix (Hardening A--G)

| Phase | Check |
|-------|-------|
| C | Transcript persist/flush call sites preserved |
| D | Budget reserve calls unchanged in moved code |
| E | Memory recall injection points unchanged |
| F | Comms sanitization on all paths |
| stability-03 | Factory cache + guardrail injection intact |

## Rollback / compatibility

- Split PRs revert independently if characterization tests fail.
- REST factory: feature flag `server.use_legacy_toolkit_build=false` default new (optional one-release legacy).

## Dependencies

- **Phase 0** -- test drift fixed; temporary line waiver removed after split.
- **Phase 1** -- restart/timeout semantics stable before large cycle moves (recommended).

## Risks and YAGNI cuts

| Risk | Mitigation |
|------|------------|
| Mechanical split breaks subtle phase order | Characterization tests mandatory first |
| REST factory over-includes dangerous tools | Explicit minimal allowlist reviewed in PR |

**YAGNI:** Split `loop.py` further; HiveStore decomposition; CLI split.

## Finding labels

| Finding | Label |
|---------|-------|
| agent_cycle.py over 600 lines | **Verified defect** |
| REST CommsToolkit no guardrails | **Verified defect** |
| REST smaller toolkit set | **By design** |
| HiveStore/Agent/CLI size | **Backlog** (optional) |
