# Phase G -- Operator DX / config truth

## Goal

Align **operator-facing behavior with documentation**: honest config hot-reload semantics, REST docs for pause/budget/daemon controls, cheaper heartbeat wake path, toolkit instance caching, and consistent goal-generation metering.

## Why (problems addressed -- bullet list with severity)

- **P1:** `PATCH /config` partial hot-reload -- only fields read via `get_config()` each heartbeat refresh (e.g. `cycle_timeout`, `max_concurrent_agents` in `src/hive/daemon/heartbeat.py`); guardrails, budget, approvals, plugins cached at daemon init (`src/hive/server/routes/system.py`, `src/hive/daemon/loop.py`).
- **P1:** REST docs drift -- pause/budget/daemon endpoints may lag implementation (`docs/guide/rest-api.md` vs `src/hive/server/routes/system.py`, `agents.py`).
- **P2:** Toolkit rebuild every pursuit cycle -- `_build_toolkits()` --> `ToolkitFactory.build()` allocates full toolkit list per agent per cycle (`src/hive/daemon/loop.py`, `toolkit_factory.py`).
- **P2:** Wake source inefficiencies -- `CompositeWakeSource` polls nudges/schedules (`src/hive/daemon/wakeup.py`, `tests/test_wakeup.py`); potential redundant store queries each sleep.
- **P2:** `GeneratedGoal` soft metering -- custom strategy path records budget after save block; existence path records inside loop; inconsistent ordering vs Phase D reservation.
- **P2:** `budget_usd=0` operator footgun -- document + CLI warnings (overlap Phase D persistence label).

## Related issues bundled

| ID | Finding |
|----|---------|
| DX-CONFIG-01 | PATCH /config implied full hot-reload |
| DX-CONFIG-02 | REST docs drift |
| DX-PERF-01 | Per-cycle toolkit allocation |
| DX-PERF-02 | Wake loop polling cost |
| DX-METER-01 | GeneratedGoal / strategy budget ordering |
| DX-API-01 | `run_once` vs daemon `run` behavioral gaps (document) |

## Current state (files)

| Area | Location | Behavior today |
|------|----------|----------------|
| Config patch | `src/hive/server/routes/system.py` | Writes YAML; no daemon notify |
| Config read | `src/hive/config.py` `get_config()` | Reloads from disk when called |
| Daemon init | `src/hive/daemon/loop.py` | Builds guardrails, budget, factory once |
| Heartbeat | `src/hive/daemon/heartbeat.py` | Comments claim PATCH works for some keys |
| Toolkits | `src/hive/daemon/toolkit_factory.py` | New list each `build()` |
| Wake | `src/hive/daemon/wakeup.py` | Composite sources |
| Docs | `docs/guide/rest-api.md`, `docs/guide/daemon-mode.md` | May omit reload matrix |

## Proposed changes (numbered)

1. **Config reload contract document + code table:**
   - Publish matrix in `docs/guide/daemon-mode.md`: Hot / restart-required / unsupported per config key.
   - Implement `HiveDaemon.reload_config()` for **safe** subsets: `daemon.heartbeat`, `daemon.cycle_timeout`, `daemon.max_concurrent_agents`, `logging.*`.
   - For guardrails/budget/plugins: either apply via `reload_config()` rebuilding components or return `409` from PATCH with `restart_required: true` field in API response.

2. **REST API doc sync:**
   - Audit routes in `src/hive/server/routes/` against `docs/guide/rest-api.md`: `/daemon/pause`, `/daemon/resume`, `/budget`, `/config` PATCH behavior, agent pause/resume.
   - Add OpenAPI-style table for reload semantics.

3. **Toolkit cache per agent:**
   - In `ToolkitFactory` or `AgentContextCache`, cache `build(agent_id)` result; invalidate on plugin hot-load (`invalidate_tool_names_cache` already exists), workspace change, profile tool list change.
   - Metric: same toolkit instance reused across cycles in integration test.

4. **Wake loop cleanup:**
   - Debounce nudge polling; single SQL for pending nudges across agents if feasible.
   - Config `daemon.wake_poll_interval` default aligned with heartbeat.

5. **GeneratedGoal metering alignment:**
   - Centralize generation spend recording before goal save (prepare for Phase D reservation); shared helper from Phase B.

6. **CLI improvements:**
   - `hive config diff` or `hive daemon` output lists stale vs live config when PATCH applied.
   - Cross-link [system overview](../guide/system-overview.md).

## Non-goals

- Full dynamic plugin unload/reload without restart.
- Rewriting REST API versioning.
- Merging `hive run` and daemon pursuit (document gap only).

## Risks / rollback

| Risk | Mitigation |
|------|------------|
| Stale cached toolkits after config change | Explicit invalidation hooks |
| Partial reload leaves inconsistent guardrails | Default to restart-required for safety fields |
| Toolkit cache holds mutable state | Toolkits must remain agent-scoped immutable after bind |

Rollback: disable cache via `daemon.toolkit_cache: false`.

## Acceptance criteria (testable)

```bash
uv run pytest tests/test_api_production.py tests/test_wakeup.py tests/test_toolkit_factory.py -v
uv run mkdocs build --strict
```

- [x] `PATCH /config` response includes `reload: applied | restart_required` per changed keys.
- [x] Changing `daemon.cycle_timeout` via PATCH affects next heartbeat without restart (existing test extended).
- [x] Changing `guardrails.enabled` via PATCH either applies live or returns restart_required (documented behavior).
- [x] `docs/guide/rest-api.md` lists pause/budget/config endpoints matching code.
- [x] Toolkit build count: 10 cycles with 1 agent --> 1 build (mock counter), invalidates on plugin load.

## Status

**Done** (2026-07-23). Shipped config reload matrix, `HiveDaemon.reload_config()`, PATCH
`reload` metadata, toolkit instance cache, wake poll interval config, unified
goal-generation save after budget commit, REST/daemon doc sync, and Phase E doc
debt (memory diagram, PersistentMemory wording).

## Suggested implementation order

1. Config reload matrix doc (truth first).
2. API response metadata + tests.
3. `reload_config()` for hot fields.
4. Toolkit instance cache + invalidation.
5. Wake polling optimization.
6. REST doc audit pass.

## Estimate

**M** (2--3 days).

## Dependencies (prior phases)

- **Phase D** -- budget reservation should integrate with reload policy (budget changes may require restart or explicit reset).
- **Phase F** -- guardrails reload policy coordinated with sanitization defaults.
