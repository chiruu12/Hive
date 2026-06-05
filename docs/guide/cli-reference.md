# CLI Reference

Complete reference for all `hive` CLI commands.

## Initialization & Lifecycle

### `hive init`

Initialize a new hive in the current directory. Creates `.hive/` with config, database, and directory structure.

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

### `hive demo survival`

3 agents (coder, gambler, philosopher) compete in a simulated economy for 30 cycles. Economy enabled, random events firing.

### `hive demo detective`

Multi-model murder mystery investigation.

```bash
hive demo detective
hive demo detective --model claude-sonnet-4-6
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
