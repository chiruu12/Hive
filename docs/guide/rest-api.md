# REST API

Hive can expose its agents over HTTP -- a FastAPI control-plane surface for
spawning, running, streaming, and approving agents from any client.

## Install and run

The server lives behind the optional `api` extra:

```bash
pip install 'hive-agent[api]'
hive init
hive serve                       # http://127.0.0.1:8000  (Swagger UI at /docs)
hive serve --port 9000 --with-daemon
```

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
| `DELETE` | `/agents/{id}` | Kill an agent |
| `POST` | `/agents/{id}/nudge` | Send a nudge -- `{"message": "..."}` |
| `POST` | `/agents/{id}/tasks` | Run a task now (synchronous) |
| `POST` | `/agents/{id}/tasks/stream` | Run a task, stream tokens over SSE |
| `GET` | `/agents/{id}/goals` | List an agent's goals |
| `GET` | `/status` | Status of all agents |
| `GET` | `/healthz` | Liveness + readiness (DB reachable) |
| `GET` | `/runs`, `/runs/{id}` | Structured run logs |
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

## Streaming (SSE)

`POST /agents/{id}/tasks/stream` returns Server-Sent Events: `token` events carry
text deltas as the model generates, then a terminal `done` event carries the final
`{status, output}` (or an `error` event).

```bash
curl -N -X POST localhost:8000/agents/coder/tasks/stream \
  -H 'Content-Type: application/json' -d '{"instruction":"summarize the repo"}'
```

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
