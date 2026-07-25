# CLI Reference

Complete reference for all `hive` CLI commands.

## Initialization & Lifecycle

### `hive init`

Initialize a new hive in the current directory. Creates `.hive/` with config, database, and directory structure.

### `hive new`

Scaffold a new Hive project directory from a template.

```bash
hive new my-swarm                    # minimal template
hive new my-swarm --template team
hive new my-swarm --force            # overwrite an existing .hive/
```

| Flag | Default | Description |
|------|---------|-------------|
| `-t`, `--template` | `minimal` | Template: `minimal`, `team`, `research` |
| `-f`, `--force` | `false` | Overwrite an existing `.hive/` directory |

### `hive start`

Start the daemon with agents.

```bash
hive start -p coder,gambler,philosopher --heartbeat 10
hive start --fresh  # ignore saved state, start clean
```

| Flag | Default | Description |
|------|---------|-------------|
| `-p`, `--profiles` | `coder` | Comma-separated profile names |
| `-b`, `--heartbeat` | `10` | Seconds between cycles |
| `--fresh` | `false` | Ignore saved state |

### `hive stop`

Stop a running daemon from another terminal. Reads `.hive/daemon.pid`, sends
SIGTERM, and waits for a graceful shutdown; escalates to SIGKILL after the
timeout.

```bash
hive stop
hive stop --timeout 60
```

| Flag | Default | Description |
|------|---------|-------------|
| `-t`, `--timeout` | `30` | Seconds to wait before SIGKILL |

### `hive restart`

Stop the running daemon (if any) and start a new one. Accepts the same
`--profiles`, `--heartbeat`, and `--fresh` flags as `hive start`.

```bash
hive restart -p coder,researcher
```

### `hive daemon`

Show daemon health: PID, uptime, agent counts, and budget. Reads the PID file
and, when the REST server is reachable (`http://127.0.0.1:8000` by default;
override with `HIVE_SERVER_URL`), queries `/status` and `/budget` for richer
detail. Exits non-zero when the daemon is not running.

```bash
hive daemon
```

### `hive spawn`

Add a new agent to a running hive.

```bash
hive spawn researcher
```

Available profiles: `coder`, `researcher`, `reviewer`, `tester`, `writer`, `gambler`, `philosopher`, `hustler`, `oracle`.

### `hive kill`

Remove an agent by name or ID.

```bash
hive kill gambler
```

### `hive nudge`

Give direction to an agent. The agent receives this as a high-priority nudge in its next goal generation cycle.

```bash
hive nudge coder "write tests for the auth module"
```

### `hive edit`

Change an agent's model or role after spawn. The daemon's provider cache
picks up model changes on the next cycle.

```bash
hive edit coder --model claude-sonnet-4-6
hive edit coder --role "senior reviewer"
```

| Flag | Default | Description |
|------|---------|-------------|
| `-m`, `--model` | | New model name |
| `-r`, `--role` | | New role description |

### `hive pause` / `hive resume`

Pause an agent (the daemon skips it each heartbeat until resumed) or resume
it back to idle. Paused agents stay paused across daemon restarts.

For a **daemon-wide freeze** that blocks all agent cycles, use
``hive daemon pause`` / ``hive daemon resume`` (see ``hive daemon`` below).

```bash
hive pause coder
hive pause --all       # pause every live agent (per-agent status, not daemon freeze)
hive resume coder
hive resume --all      # resume every paused agent
```

### `hive daemon`

Daemon health and daemon-wide freeze controls.

```bash
hive daemon            # PID, uptime, agent counts, budget (default)
hive daemon pause      # freeze all cycles (ManualPauseGuard)
hive daemon resume     # clear daemon-wide freeze
```

## Monitoring

### `hive status`

Show all agents with their roles, models, status, and active goals.

### `hive watch`

Live TUI dashboard with real-time updates.

```bash
hive watch              # 4-panel layout
hive watch --compact    # 2-panel for small terminals
hive watch --screenshot ./shots --screenshot-interval 10
```

| Flag | Default | Description |
|------|---------|-------------|
| `--compact` | `false` | 2-panel layout |
| `--screenshot` | | Directory to save screenshots |
| `--screenshot-interval` | `10` | Seconds between screenshots |

### `hive doctor`

Check environment health -- API keys, model availability, database state, directory structure.

### `hive budget`

Show the daemon-level cost budget: USD and token spend against the configured
limits (`daemon.budget_usd` / `daemon.budget_tokens`). Requires the in-process
daemon behind the REST server (`hive serve --with-daemon`); override the
server address with `HIVE_SERVER_URL`.

```bash
hive budget
```

## History & Inspection

### `hive runs`

List all recorded runs with summary stats (agents, cycles, duration).

### `hive inspect`

Show detailed summary of a recorded run -- goals, decisions, tool usage.

```bash
hive inspect <run-id>
```

### `hive replay`

Replay a past session step by step.

```bash
hive replay <session-id>
```

### `hive history`

Show an agent's goal history -- completed, abandoned, and in-progress goals.

```bash
hive history coder
hive history coder --limit 50
```

| Flag | Default | Description |
|------|---------|-------------|
| `-n`, `--limit` | `20` | Number of entries |

### `hive trace`

Display the span-tree trace for a recorded run (agents, goals, decisions,
tool calls as nested spans).

```bash
hive trace <run-id>
hive trace <run-id> --full   # include all span attributes
```

### `hive lives`

List all agent life directories with stats (cycles lived, goals completed, money earned).

### `hive biography`

Show the full biography of an agent's life -- career path, major events, peak and low points.

```bash
hive biography coder
```

## Journals & Messages

### `hive journal`

Read an agent's notepad contents.

```bash
hive journal coder
```

### `hive journals`

List all agents that have notepads.

### `hive messages`

Show an agent's A2A inbox or outbox.

```bash
hive messages coder           # inbox
hive messages coder --outbox  # outbox
```

### `hive threads`

Show active A2A message threads, optionally filtered by agent.

```bash
hive threads
hive threads --agent coder
```

## Configuration & Profiles

### `hive config`

View, set, or validate `.hive/config.yaml` without opening an editor. Set
values are validated against the config schema before saving.

```bash
hive config                          # show all config
hive config daemon.heartbeat         # show one key
hive config daemon.heartbeat 30      # set a value
hive config --validate               # validate without starting the daemon
```

### `hive profiles`

List available agent profiles, or show one profile's YAML.

```bash
hive profiles              # table of name, role, model
hive profiles coder        # print coder.yaml
```

Looks in `./profiles/` first, then `.hive/profiles/`.

## Models & Benchmarking

### `hive models`

List available models and their availability status (checks API keys and local servers).

### `hive benchmark`

Compare models on the same scenario.

```bash
hive benchmark --models anthropic:lite,openai:lite --cycles 5 --runs 3
hive benchmark --models anthropic:lite --task "Explain recursion"
```

| Flag | Default | Description |
|------|---------|-------------|
| `--models` | required | Comma-separated model specs |
| `--task` | | Single task to benchmark |
| `--cycles` | `5` | Cycles per run |
| `--runs` | `1` | Runs per model |
| `--output` | | Output file path |

## Export

### `hive export`

Export a run as a standalone HTML report.

```bash
hive export <run-id>
hive export <run-id> --output report.html
```

## Demos

### `hive demo`

Run a demo from the demo registry. Omit the name to list what's available.

```bash
hive demo               # list available demos
hive demo survival      # 3 agents, 30 cycles, economy on
hive demo detective     # multi-model murder mystery
hive demo survival -q   # suppress output
```

## Interactive Agent

### `hive agent chat`

Start an interactive agent session with tools.

```bash
hive agent chat
hive agent chat --model claude-sonnet-4-6 --no-tools
hive agent chat --workspace ./my-project
```

| Flag | Default | Description |
|------|---------|-------------|
| `--model` | `claude-haiku-4-5` | Model to use |
| `--no-tools` | `false` | Disable file/shell/git tools |
| `--workspace` | `.` | Working directory |

### `hive agent run`

Run an agent from a YAML config file.

```bash
hive agent run examples/06_cli_agent.yaml
```

## REST API Server

### `hive serve`

Serve the REST API (requires the `api` extra: `pip install 'hive-agent[api]'`).
See the [REST API guide](rest-api.md) for endpoints.

```bash
hive serve
hive serve --port 9000 --with-daemon
```

| Flag | Default | Description |
|------|---------|-------------|
| `--host` | `127.0.0.1` | Bind address |
| `--port` / `-p` | `8000` | Port |
| `--with-daemon` | `false` | Run the heartbeat loop in-process |
| `--reload` | `false` | Auto-reload on code changes (dev) |

## Human-in-the-Loop Approvals

### `hive approvals`

List all pending tool approvals across agents.

```bash
hive approvals
```

### `hive approve` / `hive deny`

Resolve a pending approval. After `approve` the agent runs the tool next cycle;
after `deny` it sees the denial and re-plans.

```bash
hive approve ap-1a2b3c
hive deny ap-1a2b3c --reason "too risky"
```

See [Human-in-the-Loop Approvals](daemon-mode.md#human-in-the-loop-approvals) for setup.
