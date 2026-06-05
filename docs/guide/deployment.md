# Deployment

Hive ships a `Dockerfile` and `docker-compose.yml` that run the REST API and the
heartbeat daemon together in one container -- the agent OS in your own infrastructure.

## Docker Compose (one command)

```bash
ANTHROPIC_API_KEY=sk-... docker compose up --build
```

- Control plane: <http://localhost:8000/>
- API docs: <http://localhost:8000/docs>

Provider keys are read from your shell (or a `.env` file) and passed through; set only
the ones you use (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GROQ_API_KEY`,
`HIVE_DEFAULT_MODEL`). Agent state, logs, and workspaces persist in the `hive_state`
volume across restarts.

## Plain Docker

```bash
docker build -t hive-agentos .
docker run -p 8000:8000 \
  -e ANTHROPIC_API_KEY=sk-... \
  -v hive_state:/data \
  hive-agentos
```

## How the image is built

- **Multi-stage**: a build stage installs the package (with the `[api]` extra) into a
  self-contained venv via `uv sync --no-editable`; the slim runtime stage copies only
  that venv.
- Runs as a **non-root** user; all writable state lives under `/data` (the working
  directory and the mount point), so the container filesystem stays read-only-friendly.
- The entrypoint runs the idempotent `hive init` then
  `hive serve --host 0.0.0.0 --port 8000 --with-daemon`, so a single process serves
  HTTP and drives agents.

## Scaling notes

`hive serve` (without `--with-daemon`) is **stateless** and can run behind a load
balancer with several replicas, all reading/writing one shared `.hive/hive.db` (SQLite
WAL handles concurrent access). Run **one** `--with-daemon` instance (or a standalone
`hive start`) to drive the heartbeat, and scale the API replicas separately. For
heavier multi-writer loads, point the daemon and API at shared storage for `/data`.

## Production checklist

- Set real provider API keys via secrets, not in the image.
- Put the API behind TLS and authentication (the server binds `0.0.0.0` in the
  container; restrict exposure at the proxy/ingress).
- Back up the `/data` volume (it holds the SQLite DB, event logs, and workspaces).
- Tune `.hive/config.yaml` (`daemon.heartbeat`, `daemon.max_concurrent_agents`) for
  your workload; enable `approval` and `guardrails` for untrusted use.
