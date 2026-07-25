# Stability 02: Extension points -- wire, shrink, or delete

## Goal

Resolve YAGNI extension points that create **false expectations**: either register them in the default daemon with tests and docs, or remove/shrink them so the codebase matches what actually runs.

**Status:** implemented (2026-07-22) on branch `fix/framework-hardening`.

## Why (stability)

Dead extension points confuse operators and reviewers. Before this plan:

- Docs equated `hive pause --all` with `ManualPauseGuard`, but CLI pause only sets `AgentStatus.PAUSED` in SQLite.
- `NudgeWakeSource` existed but was never registered; `hive nudge` wrote to SQLite only, not the wake directory.
- `DefaultSwarmPolicy` sounded active but only logged routing hints.
- Six `CyclePhase` values with hooks, but only `CostBudgetGuard` was registered (on two phases).
- `StoreProtocol` had no test fake despite ~45 methods.

## Decision table

| Extension | Decision | Rationale |
|-----------|----------|-----------|
| `ManualPauseGuard` | **Wire** | Daemon-wide freeze is distinct from per-agent pause; register on all six phases; expose `HiveDaemon.pause()`/`resume()`, `.hive/daemon.paused` file IPC, `hive daemon pause`/`resume`, `POST /daemon/pause`/`resume`. |
| Per-agent pause (`AgentStatus.PAUSED`) | **Keep** | Already wired in heartbeat filter + CLI + REST; unchanged semantics for `hive pause <agent>` and `hive pause --all`. |
| `NudgeWakeSource` | **Wire** | Register by default; `hive nudge` and REST nudge also touch `<hive>/nudges/<id>.json` so wake fires before next heartbeat. |
| `FileWakeSource` | **Config-gate** | Not registered by default. `daemon.watch_files: []` — one `FileWakeSource` per path when non-empty. |
| `A2AWakeSource` | **Keep** | Already wired. |
| `DefaultSwarmPolicy` | **Keep (opt-in)** | Renamed docstrings: log-only routing hints, no autonomous routing. |
| Default swarm policy | **Shrink → Passive** | `HiveDaemon` defaults to `PassiveSwarmPolicy()`; pass `DefaultSwarmPolicy()` to opt into verbose routing logs. |
| Phase ceremony (6 phases + hooks) | **Keep, document** | Low risk to delete; external `phase_enter` subscribers may exist. Document which phases have built-in guards. Collapse deferred (grep shows no plugin subscribers today). |
| `StoreProtocol` | **Shrink (audit)** | Audit confirms all listed methods are used by daemon, server, tools, or agents. Add `tests/fakes/minimal_store.py` fake; no PostgreSQL backend. |
| Stale docs | **Fix** | `production-readiness-sprint.md`, `daemon-mode.md`, `extending/index.md`, `hardening-guide.md`, `security-audit-2026-07-22.md` banner. |

## Current state (after implementation)

| Extension | Files | Wired? |
|-----------|-------|--------|
| `ManualPauseGuard` | `gates.py`, `loop.py` | Yes — all six phases |
| Per-agent pause | `heartbeat.py`, CLI, `server/routes/agents.py` | Yes |
| `A2AWakeSource` | `wakeup.py`, `loop.py` | Yes |
| `NudgeWakeSource` | `wakeup.py`, `loop.py` | Yes |
| `FileWakeSource` | `wakeup.py`, `loop.py` (config-gated) | When `daemon.watch_files` non-empty |
| `SwarmPolicy` | `swarm_policy.py`, `loop.py` | Yes — default `PassiveSwarmPolicy` |
| `CyclePhase` / phase hooks | `phase.py`, `agent_cycle.py` | Ceremony + guard veto |
| `StoreProtocol` | `memory/protocol.py` | Audited + `tests/fakes/minimal_store.py` |
| Stale security doc | `docs/security-audit-2026-07-22.md` | Superseded banner added |

## Pause semantics (operator reference)

| Mechanism | Scope | Storage | CLI | REST |
|-----------|-------|---------|-----|------|
| Per-agent pause | One agent skipped each heartbeat | SQLite `AgentStatus.PAUSED` | `hive pause <agent>`, `hive pause --all` | `POST /agents/{id}/pause` |
| Daemon freeze | All agent cycles blocked at phase guards | In-memory + `.hive/daemon.paused` | `hive daemon pause` / `hive daemon resume` | `POST /daemon/pause` / `POST /daemon/resume` |

`hive pause --all` pauses every live agent individually — it does **not** set `ManualPauseGuard`.

## Implementation details

### ManualPauseGuard (wire)

1. `self._pause_guard = ManualPauseGuard()` on `HiveDaemon`; register on all `CyclePhase` values with `fail_closed=True`.
2. `pause()` / `resume()` flip guard + write/delete `.hive/daemon.paused`.
3. Heartbeat syncs guard from file each cycle (CLI/file IPC when REST unavailable).
4. REST endpoints require in-process daemon (`hive serve --with-daemon`).

### Wake sources

1. `NudgeWakeSource(hive_dir / "nudges")` registered in `__init__`.
2. `touch_nudge_wake_file(hive_dir, nudge_id)` called from CLI, REST, API, MCP nudge paths.
3. `daemon.watch_files: list[str]` in config; register `FileWakeSource` per path when set.

### SwarmPolicy (shrink default)

- Default: `PassiveSwarmPolicy()` (debug-level log only).
- Opt-in: `HiveDaemon(..., swarm_policy=DefaultSwarmPolicy())` for INFO/WARNING routing-hint logs.
- Neither policy mutates goals or routes tasks autonomously.

### Phase ceremony (keep)

Built-in guards today:

| Phase | Guards |
|-------|--------|
| `approval_gate` | `ManualPauseGuard` |
| `suffering_escalation` | `ManualPauseGuard` |
| `context_assembly` | `ManualPauseGuard` |
| `goal_pursuit` | `ManualPauseGuard`, `CostBudgetGuard` |
| `goal_generation` | `ManualPauseGuard`, `CostBudgetGuard` |
| `cleanup` | `ManualPauseGuard` |

### StoreProtocol (audit + fake)

Grep audit (2026-07-22): every protocol method is referenced by at least one of daemon, server, CLI, tools, agents, or memory helpers. No methods removed — protocol already matches consumer surface. Added `MinimalStore` fake for unit tests.

## Non-goals

- Implementing full swarm task routing.
- PostgreSQL store backend.
- Removing phase hooks entirely (defer until grep confirms zero external subscribers).
- Security default changes (guardrails, approval).
- Repurposing `hive pause --all` to use `ManualPauseGuard`.

## Risks / rollback

| Decision | Risk | Rollback |
|----------|------|----------|
| Wire `ManualPauseGuard` | Operators confuse agent vs daemon pause | Doc table + distinct CLI subcommands |
| Default `PassiveSwarmPolicy` | Tests expecting `DefaultSwarmPolicy` INFO logs | Explicit `DefaultSwarmPolicy()` in tests |
| Config-gated `FileWakeSource` | Unknown external users watch ad-hoc paths | Empty default; document `watch_files` |
| StoreProtocol audit | No runtime change | Fake store is test-only |

## Acceptance criteria (testable)

```bash
uv run pytest tests/test_phase.py tests/test_wakeup.py tests/test_swarm_policy.py tests/adversarial/test_daemon_resilience.py -v
uv run pytest tests/test_solid_validation.py -v
uv run mypy src/hive/daemon/ src/hive/agents/swarm_policy.py
```

- [x] `NudgeWakeSource` registered by default; nudge wake file triggers wake (unit test).
- [x] `ManualPauseGuard` registered on all phases; `daemon.pause()` blocks goal phases; per-agent `AgentStatus.PAUSED` independent.
- [x] CLI help distinguishes agent pause vs `hive daemon pause`.
- [x] Default swarm policy is passive; docs state no autonomous routing.
- [x] `MinimalStore` satisfies `StoreProtocol`; `HiveStore` still conforms.
- [x] Stale doc cross-links updated; no contradictory "pause --all uses ManualPauseGuard" claims.

## Implementation order (executed)

1. Doc fixes (zero runtime risk).
2. Wire `NudgeWakeSource` + nudge wake file + tests.
3. Wire `ManualPauseGuard` + API/CLI + tests.
4. SwarmPolicy default shrink + docs.
5. StoreProtocol audit + `MinimalStore` fake.
6. Config-gated `FileWakeSource`.

## Estimate

**M** (2–3 days) — completed as single PR on stability track.
