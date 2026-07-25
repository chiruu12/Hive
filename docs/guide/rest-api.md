# REST API

Hive can expose its agents over HTTP -- a FastAPI control-plane surface for
spawning, running, streaming, and approving agents from any client.

!!! warning "Authentication is opt-in"
    The REST API binds to `127.0.0.1` and runs **without authentication by
    default** (the local-first zero-config posture). Before exposing it beyond
    localhost, set a shared API key -- `server.api_key` in `.hive/config.yaml`
    or the `HIVE_API_KEY` env var -- and every route except `/healthz` and the
    static UI/docs shells will require a matching `X-Hive-Key` header.
    **Non-loopback binds** (`hive serve --host 0.0.0.0`, etc.) refuse to start
    without a key; loopback (`127.0.0.1`, `localhost`, `::1`) stays keyless.
    For development-only LAN exposure without a key, set
    `HIVE_API_ALLOW_INSECURE=1` (discouraged).
    `X-Hive-User` remains a tenant *routing hint*, not a security boundary:
    agents are a single shared pool in this release, so the agents and approval
    endpoints are a shared operator surface. For multi-user or internet-facing
    deployments, still front it with your own TLS/auth proxy; per-request
    session rows are isolated by user, and agent ownership / RBAC is on the
    roadmap.

## Authentication, CORS, and session expiry

```yaml
# .hive/config.yaml
server:
  api_key: ""            # set to require X-Hive-Key on data routes (or HIVE_API_KEY)
  cors_origins: []       # e.g. ["http://localhost:5173"]; empty = no CORS headers
  session_ttl_hours: 0   # mark running sessions 'expired' after N idle hours; 0 = never
```

With a key set, pass it on every request; the control plane has a `key` field
in its header bar that does the same:

```bash
curl -H "X-Hive-Key: $HIVE_API_KEY" http://127.0.0.1:8000/agents
```

Session expiry is enforced by the retention janitor (`retention.enabled`) and
on session resolution: an expired session 404s when addressed by id, and a
`session_key` lookup falls through to a fresh session.

## Pagination

`GET /agents`, `/approvals`, `/agents/{id}/approvals`, `/sessions`, and
`/runs` accept `limit` (1-1000) and `offset` query parameters. Omitting
`limit` returns the full result set (backward compatible).

## Install and run

The server lives behind the optional `api` extra:

```bash
pip install 'hive-agent[api]'
hive init
hive serve                       # http://127.0.0.1:8000
hive serve --port 9000 --with-daemon
```

Open `http://127.0.0.1:8000/` for the **control plane** (a browser dashboard),
`/docs` for the Swagger API explorer.

## Control plane

The page at `/` is a self-contained dashboard (no build step) that talks to the API
in the same process -- your data never leaves your machine. It shows the pending
**approval queue** (with approve/deny buttons), the **agents** list with live status,
and **sessions**, auto-refreshing every few seconds. Set the tenant in the `user`
field (sent as `X-Hive-User`).

| Flag | Default | Meaning |
|------|---------|---------|
| `--host` | `127.0.0.1` | Bind address (local-first by default) |
| `--port` / `-p` | `8000` | Port |
| `--with-daemon` | off | Run the heartbeat loop in-process |
| `--reload` | off | Auto-reload on code changes (dev) |

Two modes share the same `.hive/hive.db` (WAL handles concurrent writers):

- **Stateless (default).** The server only reads/writes the database. Run a
  separate `hive start` to actually drive agent cycles. The server scales
  horizontally with no session affinity.
- **Embedded daemon (`--with-daemon`).** The heartbeat loop runs in the same
  process as a background task -- a single command serves HTTP and drives agents.

## Endpoints

Interactive docs are auto-generated at `/docs` (Swagger) and `/redoc`.

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/agents` | Spawn from a preset -- `{"preset": "coder", "model": "..."}` |
| `GET` | `/agents` | List agents |
| `GET` | `/agents/{id}` | Agent detail |
| `PATCH` | `/agents/{id}` | Update model/role -- `{"model": "...", "role": "..."}` |
| `DELETE` | `/agents/{id}` | Kill an agent |
| `POST` | `/agents/{id}/nudge` | Send a nudge -- `{"message": "..."}` (stored raw; sanitized at goal-generation) |
| `POST` | `/agents/{id}/pause` | Pause -- the daemon skips the agent until resumed |
| `POST` | `/agents/{id}/resume` | Resume a paused agent |
| `GET` | `/agents/{id}/history` | Goal history (`limit` 1-200, default 20) |
| `POST` | `/agents/{id}/tasks` | Run a task now (synchronous) |
| `POST` | `/agents/{id}/tasks/stream` | Run a task, stream tokens over SSE |
| `GET` | `/agents/{id}/goals` | List an agent's goals |
| `GET` | `/status` | Status of all agents |
| `GET` | `/healthz` | Liveness + readiness (DB reachable) |
| `GET` | `/metrics` | Prometheus-format agent/goal gauges |
| `GET` | `/budget` | Daemon budget status (503 without `--with-daemon`) |
| `POST` | `/budget/reset` | Reset spent budget counters (503 without daemon) |
| `POST` | `/daemon/pause` | Daemon-wide freeze (`ManualPauseGuard`; 503 without daemon) |
| `POST` | `/daemon/resume` | Clear daemon-wide freeze (503 without daemon) |
| `GET` | `/config` | Current config (secrets redacted) |
| `PATCH` | `/config` | Merge fields into `.hive/config.yaml`; returns `reload` map |
| `GET` | `/runs`, `/runs/{id}` | Structured run logs |
| `GET` | `/runs/{id}/trace` | Span-tree trace for a run |
| `GET` | `/approvals` | Global pending-approval queue |
| `GET` | `/agents/{id}/approvals` | Pending approvals for one agent |
| `POST` | `/agents/{id}/approvals/{approval_id}` | Approve or deny |
| `POST/GET` | `/sessions` | Create / list sessions |
| `GET/DELETE` | `/sessions/{id}` | Get / close a session |

### Example

```bash
curl -X POST localhost:8000/agents -d '{"preset":"coder"}' -H 'Content-Type: application/json'
curl localhost:8000/status
```

## Operations endpoints

**Config.** `GET /config` returns `persisted` (YAML on disk), `effective` (disk +
env overrides), optional `live` (in-process cache when the daemon is running),
and `restart_required_fields` documenting keys that need `hive restart`. Secret
values (`server.api_key`) are replaced by `***` in every view. `PATCH /config`
deep-merges the request body into `.hive/config.yaml` -- the result is validated
against the config schema before writing, so an invalid patch returns `400` and
leaves the file untouched. The response shape is:

```json
{
  "config": { "...": "..." },
  "reload": {
    "daemon.heartbeat": "applied",
    "guardrails.enabled": "restart_required"
  }
}
```

Each key in `reload` is either `applied` (hot-reloaded on the in-process daemon
when `hive serve --with-daemon`) or `restart_required`. See
[Daemon Mode -- Config hot-reload vs restart](daemon-mode.md#config-hot-reload-vs-restart)
for the full matrix.

```bash
curl -X PATCH localhost:8000/config \
  -H 'Content-Type: application/json' -d '{"daemon": {"heartbeat": 30}}'
```

**Daemon freeze.** `POST /daemon/pause` activates `ManualPauseGuard` for every
agent cycle; `POST /daemon/resume` clears it. These mirror `hive daemon pause`
/ `hive daemon resume` and require the in-process daemon (`503` in stateless
mode). Per-agent pause remains `POST /agents/{id}/pause` and `/resume`.

**Budget.** `GET /budget` reports the daemon-level cost kill-switch
(`daemon.budget_usd` / `daemon.budget_tokens`): spent, remaining, reserved,
and whether the limit has been exceeded. It requires the in-process daemon
(`hive serve --with-daemon`); in stateless mode it returns `503`.
`POST /budget/reset` clears spent counters (and the persisted ledger when
`daemon.budget_persist` is enabled).

**Metrics.** `GET /metrics` serves Prometheus-format gauges: agents by status
(`hive_agents_working`, `hive_agents_idle`, `hive_agents_waiting`,
`hive_agents_paused`, `hive_agents_dead`) and `hive_goals_active` -- point a
Prometheus scrape job at it directly.

**Pause/resume.** `POST /agents/{id}/pause` sets the agent to `paused`; the
daemon skips paused agents each heartbeat and they stay paused across daemon
restarts until `POST /agents/{id}/resume` sets them back to `idle`.

!!! note "REST tasks vs daemon pursuit"
    `POST /agents/{id}/tasks` and `/tasks/stream` run the standalone runtime
    `Agent.run()` path (single session, no suffering/goal lifecycle). The
    embedded daemon drives multi-heartbeat pursuit, goal generation, and budget
    guards. They share SQLite but use different toolkit sets: REST one-shot
    builds a **secure-minimal** subset via
    `hive.daemon.secure_toolkit_factory.build_minimal` (memory, comms, optional
    world) with guardrails injected on comms; the daemon heartbeat uses the full
    `ToolkitFactory` (file, shell, web, sub_agents, orchestrator, etc.). See
    [System overview](system-overview.md).

**Nudges.** `POST /agents/{id}/nudge` stores operator text for the target agent
(up to 4k characters). The daemon sanitizes pending nudges at **read** time
before assembling the goal-generation prompt: structural cleanup (control
chars, simple HTML tags) always runs; when `guardrails.enabled` is true, the
same prompt-injection pipeline used for inter-agent content can block or
redact matches. Nudges are not re-sanitized on write -- treat the REST surface
as trusted only when bound to localhost or protected by `server.api_key`.

**Schedules (agent tools).** Agents manage recurring goals via the schedule
toolkit (`schedule_goal`, `list_schedules`, `cancel_schedule`). `cancel_schedule`
only disables schedules owned by the calling agent; attempting to cancel another
agent's schedule returns an error and leaves the row unchanged.

## Streaming (SSE)

`POST /agents/{id}/tasks/stream` returns Server-Sent Events: `token` events carry
text deltas as the model generates, then a terminal `done` event carries the final
`{status, output}` (or an `error` event).

```bash
curl -N -X POST localhost:8000/agents/coder/tasks/stream \
  -H 'Content-Type: application/json' -d '{"instruction":"summarize the repo"}'
```

When **guardrails are enabled**, token deltas are suppressed (they would bypass
OUTPUT-stage redaction); the stream opens with a single `info` event
(`token_streaming_suppressed_by_guardrails`) and delivers only the redacted final
output in the `done` event. Clients should treat `info` as a cue to show a
non-incremental progress indicator.

## Sessions and multi-tenancy

Requests carry a tenant via the `X-Hive-User` header (default `default`). A session
groups task runs, transcripts, and token accounting under one `session_id`, isolated
per user -- one tenant cannot read another's sessions. Task requests resolve a
session by explicit `session_id`, then `(user, session_key)`, then create a fresh one.

```bash
curl -X POST localhost:8000/sessions -H 'X-Hive-User: alice' \
  -H 'Content-Type: application/json' -d '{"agent_id":"coder","session_key":"chat-1"}'
```

## Human-in-the-loop approvals

See [Daemon Mode](daemon-mode.md#human-in-the-loop-approvals) for how gated tools
pause an agent. The pending request appears in the approval queue; resolve it:

```bash
curl localhost:8000/approvals
curl -X POST localhost:8000/agents/coder/approvals/ap-123 \
  -H 'Content-Type: application/json' -d '{"decision":"approve"}'
```

Or from the CLI: `hive approvals`, `hive approve <id>`, `hive deny <id> --reason "..."`.
