# Production Readiness Sprint — P0+P1 Items

## Context
The framework has solid internals (1461 tests, clean SOLID) but is missing the operational glue that makes it usable in practice. This sprint adds the commands, endpoints, and safety rails needed for real-world use.

---

## Track 1: `hive stop` + `hive restart`
**Goal**: Stop/restart the daemon from another terminal.

- Read `.hive/daemon.pid`, validate PID is alive, send SIGTERM
- Wait for graceful shutdown (poll PID until dead, up to timeout)
- `restart` = stop + start
- Fix broken `scripts/stop.sh`

**Files**: `src/hive/cli/main.py` (new commands)

---

## Track 2: `hive config show|set|validate`
**Goal**: View, edit, and validate config from CLI.

- `hive config` — show current config (merged from file + env)
- `hive config set <key> <value>` — update a config field
- `hive config validate` — check config without starting daemon

**Files**: `src/hive/cli/main.py` (new command), `src/hive/config.py` (add set/validate methods)

---

## Track 3: `hive edit <agent>`
**Goal**: Change agent properties after spawn.

- `hive edit <agent> --model <model>` — switch model
- `hive edit <agent> --role <role>` — change role
- Daemon's provider cache already detects model changes

**Files**: `src/hive/cli/main.py` (new command), `src/hive/server/routes/agents.py` (PATCH endpoint)

---

## Track 4: Log Rotation
**Goal**: Prevent unbounded log growth.

- Size-based rotation in `LogWriter`
- Configurable max size + retention count
- Add `log_max_bytes` and `log_max_files` to config

**Files**: `src/hive/logging/writer.py`, `src/hive/config.py`

---

## Track 5: Daemon Health Command
**Goal**: Show daemon status, uptime, cycles, PID.

- `hive daemon` — show PID, uptime, cycle count, budget, agent summary
- Read PID file, check process is alive
- If server running, query `/status` and `/budget`

**Files**: `src/hive/cli/main.py` (new command)

---

## Track 6: Agent History CLI
**Goal**: Show what an agent did over time.

- `hive history <agent>` — show goals, status changes, tool calls
- Read from DB (goals table) and log files

**Files**: `src/hive/cli/main.py` (new command)

---

## Track 7: Profiles CLI
**Goal**: List and inspect available profiles.

- `hive profiles` — list all profiles in `profiles/` directory
- `hive profiles show <name>` — display a profile's YAML

**Files**: `src/hive/cli/main.py` (new command)

---

## Track 8: Pause/Resume
**Goal**: Pause/resume individual agents or freeze the whole daemon.

- `hive pause <agent>` — set agent status to paused (per-agent, SQLite)
- `hive resume <agent>` — restore to idle
- `hive pause --all` — pause every live agent individually (not daemon freeze)
- `hive daemon pause` / `hive daemon resume` — daemon-wide `ManualPauseGuard` + `.hive/daemon.paused`
- `POST /agents/{id}/pause` and `POST /agents/{id}/resume` — per-agent
- `POST /daemon/pause` and `POST /daemon/resume` — in-process daemon freeze (`hive serve --with-daemon`)

**Files**: `src/hive/cli/main.py`, `src/hive/server/routes/agents.py`

---

## Track 9: `PATCH /agents/{id}` API
**Goal**: Update agent properties via REST.

- Update model, role, status fields
- Returns updated agent state

**Files**: `src/hive/server/routes/agents.py`

---

## Track 10: Config API Endpoints
**Goal**: Read/write config via REST.

- `GET /config` — return current config
- `PATCH /config` — update config fields (partial)

**Files**: `src/hive/server/routes/system.py`

---

## Track 11: `GET /agents/{id}/history` API
**Goal**: Agent timeline via REST.

- Return goals, status changes, events for an agent
- Paginated with limit/offset

**Files**: `src/hive/server/routes/agents.py`

---

## Implementation Order
1. Track 1: stop/restart (critical operational gap)
2. Track 5: daemon health (quick, high value)
3. Track 2: config CLI (setup experience)
4. Track 3: agent edit + Track 9: PATCH API (agent management)
5. Track 7: profiles CLI (discovery)
6. Track 4: log rotation (safety)
7. Track 6: agent history + Track 11: history API (observability)
8. Track 8: pause/resume (control)
9. Track 10: config API (completeness)
