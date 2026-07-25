# Stabilization Phase 4 -- Operator truth and parity

## Problem statement

Operators cannot trust CLI output, config writes, or docs to reflect **effective runtime state**. Standalone daemon mode diverges from REST-embedded mode for budget and profiles. Dead config keys and MCP trust boundaries are undocumented.

### Exact files and functions

| Finding | Location | Label |
|---------|----------|-------|
| Budget CLI requires REST | `src/hive/cli/main.py` budget/status commands | **Verified defect** |
| Standalone start enforces budget | `src/hive/daemon/loop.py`, `budget.py` | Correct; CLI view missing |
| Config writes hide reload metadata | `cli/main.py` config set; `server/routes/system.py` PATCH | **Verified defect** |
| Effective vs persisted vs live conflated | Phase G partial; CLI still unclear | **Verified defect** |
| Profile path mismatch | `cli/main.py` `Path.cwd() / "profiles"` vs `agents/profile.py` `default_profiles_dir()` | **Verified defect** |
| Heartbeat CLI override overwritten | `heartbeat.py` disk reload on first tick | **Verified defect** |
| Dead keys `event_poll_interval`, `watch_refresh_rate` | `src/hive/config.py` | **Verified defect** (dead config) |
| `logs_dir` unused at runtime | Config vs hardcoded log paths in daemon | **Verified defect** |
| MCP smaller control surface | `mcp/server.py` vs REST routes | **By design**; docs wrong |
| Doctor missing diagnostics | `cli/main.py` doctor command | **Verified defect** |
| Config reload security | Phase G restart-required matrix | **Not a bug** -- improve visibility only |

## Scope

- Standalone budget status/reset without REST.
- Unified profile directory resolution (CLI, daemon, REST, MCP).
- CLI + REST expose effective / persisted / live config and reload status.
- Heartbeat override semantics documented; fix or explicit "ignored after reload" warning.
- Wire or remove dead config keys; wire `logs_dir` or mark deprecated.
- MCP trusted-host documentation; doctor extensions for stale PID, budget, plugins.

## Non-goals

- Hot-rebuilding guardrails/tools on config PATCH (restart-required stays correct).
- Full REST == daemon toolkit parity (Phase 5 secure-minimal factory).
- MCP feature parity with REST.
- Rewriting all operator docs (targeted updates only).

## Implementation slices

### Slice 4.1 -- Standalone budget commands

1. `hive budget status` reads `BudgetTracker` from running standalone daemon state file or hive dir persist JSON.
2. `hive budget reset` writes persist file + optional running daemon notify hook.
3. Parity tests: standalone vs REST embedded same numbers after spend.

### Slice 4.2 -- Profile directory unification

1. Single resolver: `default_profiles_dir()` with `HIVE_PROFILES_DIR` / config override.
2. Replace `Path.cwd() / "profiles"` in `cli/main.py` `start`/`spawn`.
3. Test: spawn from non-cwd hive root finds profiles.

### Slice 4.3 -- Config truth surfaces

1. `hive config show --effective|--persisted|--live` (or subcommands).
2. REST `GET /config` returns `{ persisted, live, restart_required_fields[] }`.
3. PATCH response includes `applied: hot|restart_required` per key (extend Phase G).
4. CLI prints warning when changed keys require restart.

### Slice 4.4 -- Heartbeat override semantics

1. Document: constructor/`hive start --heartbeat` applies until first `get_config()` disk reload.
2. Option A: persist heartbeat to config on CLI start.
3. Option B: warn on mismatch after reload.
4. Pick one; test documented behavior.

### Slice 4.5 -- Dead config keys and logs_dir

1. Grep consumers for `event_poll_interval`, `watch_refresh_rate`; remove or wire to wake loop.
2. Wire `logs_dir` in `HiveDaemon` / `RunLogWriter` or deprecate with migration note.
3. Update config tables in `docs/getting-started/cli-quickstart.md`.

### Slice 4.6 -- MCP trust documentation

1. Add section to `docs/guide/daemon-mode.md` or new MCP page: stdio == trusted local operator, not network auth.
2. Fix architecture diagrams implying MCP == full control plane.

### Slice 4.7 -- Doctor diagnostics

1. Extend `hive doctor`: stale PID file, duplicate daemon hint, budget persist readable, plugin load errors, profile dir exists.
2. Non-zero exit when critical issues found.

## Acceptance criteria

```bash
uv run pytest tests/cli/test_cli.py tests/test_config.py -v
uv run pytest tests/test_daemon_setup.py -v
uv run mkdocs build --strict
```

- [x] `hive budget status` works with standalone daemon (no REST).
- [x] CLI and REST spawn same profile from package `profiles/`.
- [ ] Config PATCH shows restart-required for guardrails/budget keys.
- [ ] Doctor detects stale PID and reports budget state path.
- [ ] Dead keys removed or wired; docs match.

**Status:** BLOCKERS CLEARED (B1–B3, 2026-07-25) — profile resolver unified, budget CLI/REST ledger parity, daemon status ledger fallback. Remaining slices (4.3–4.7) open.

**Re-verification (2026-07-25):** VERIFIED — 127 targeted tests, 1857 full, 243 adversarial; B1 `resolve_profiles_dir` unified, B2 budget 503 ledger fallback + REST/ledger parity, B3 optional `logs_dir` wiring.

## Regression matrix (Hardening A--G)

| Phase | Check |
|-------|-------|
| G | Reload contract extended, not contradicted |
| D | Budget persist path unchanged except CLI read access |
| F | Secure profile template still valid |

## Rollback / compatibility

- Profile path change may affect users with cwd-relative `./profiles` only -- document `profiles_dir` config.
- New CLI flags additive only.

## Dependencies

- **Phase 0** -- baseline green.
- **Phase 2** -- budget persist path stable for standalone budget commands.

## Risks and YAGNI cuts

| Risk | Mitigation |
|------|------------|
| Reading budget from file while daemon running | Document read-only snapshot; optional IPC later |

**YAGNI:** Full config UI; hot plugin reload; MCP auth layer.

## Finding labels

| Finding | Label |
|---------|-------|
| Budget CLI REST-only | **Verified defect** |
| Profile path split | **Verified defect** |
| Config reload drops security silently | **Not a bug** (restart-required correct) |
| MCP network auth expected | **Risk / hypothesis** (docs gap) |
| Dead config keys | **Verified defect** |
