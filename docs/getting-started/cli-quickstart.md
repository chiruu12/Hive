# CLI Quickstart

Run Hive as an autonomous agent OS from your terminal.

## Initialize

```bash
hive init
```

Creates a `.hive/` directory with configuration and database.

## Run the Survival Demo

The fastest way to see Hive in action:

```bash
hive demo survival
```

3 agents spawn with different personalities -- a methodical coder, a reckless gambler, and a contemplative philosopher. They compete in a simulated economy for 30 cycles (~90 seconds). Watch suffering bars diverge, journal entries get more desperate, and the gambler lose their money.

## Start Your Own Simulation

```bash
hive start -p coder,gambler,philosopher
```

Spawns agents from YAML profiles and starts the daemon heartbeat loop.

## Watch Live

```bash
hive watch
```

4-panel TUI dashboard:

1. **Agents** -- name, role, status, current goal, suffering bar, happiness emoji
2. **Activity Feed** -- events, journal entries, A2A messages, economy events
3. **Vitals** -- tokens, cost, goals completed/abandoned, money balance
4. **Drama** -- highlight reel of most interesting recent events

For small terminals:

```bash
hive watch --compact
```

## Interact with Agents

```bash
# Check status
hive status

# Give an agent direction
hive nudge coder "write tests for the auth module"

# Spawn additional agents
hive spawn researcher

# Remove an agent
hive kill gambler

# Health check
hive doctor
```

## Run the Detective Demo

Multi-model murder mystery with 3 agents investigating a case:

```bash
hive demo detective
```

## CLI Reference

| Command | Description |
|---------|-------------|
| `hive init` | Initialize `.hive/` directory |
| `hive new <name>` | Scaffold a project from a template |
| `hive start -p <profiles>` | Start daemon with named profiles |
| `hive stop` / `hive restart` | Stop or restart the daemon from another terminal |
| `hive daemon` | Daemon health: PID, uptime, agents, budget |
| `hive watch` | Live TUI dashboard |
| `hive watch --compact` | 2-panel compact dashboard |
| `hive status` | Show agent status, goals, suffering |
| `hive spawn <profile>` | Add an agent |
| `hive kill <agent>` | Terminate an agent |
| `hive edit <agent> --model <m>` | Change an agent's model or role |
| `hive pause <agent>` / `hive resume <agent>` | Skip / re-include an agent in the heartbeat |
| `hive nudge <agent> <msg>` | Send direction to an agent |
| `hive history <agent>` | Goal history for an agent |
| `hive config [key] [value]` | Show, set, or validate config |
| `hive profiles [name]` | List profiles or show one |
| `hive budget` | Daemon cost kill-switch status |
| `hive doctor` | Health check and diagnostics |
| `hive demo` | List and run demos (survival, detective) |
| `hive agent chat` | Interactive single-agent with tools |
| `hive agent run <yaml>` | Run agent from YAML config |

## Configuration

All config lives in `.hive/config.yaml`:

```yaml
daemon:
  heartbeat: 10        # seconds between cycles
  budget_usd: 0.0      # daemon-wide USD spend kill-switch; 0 = unlimited (off)
  budget_tokens: 0     # daemon-wide token kill-switch; 0 = unlimited (off)
  guards_fail_closed: true  # safety guards block phases on internal errors

model:
  default_model: claude-haiku-4-5
  temperature: 0.0

economy:
  enabled: true
  starting_balance: 100.0

suffering:
  threshold_crisis: 0.90
  max_stressors: 5

approval:                 # human-in-the-loop tool gating (off by default)
  enabled: false
  require_for: []         # tool names always gated
  auto_approve: []        # tool names never gated (overrides a tool's own flag)
  timeout_cycles: 0       # auto-deny after N heartbeats (0 = never)

guardrails:               # content checks on model input/output (off by default)
  enabled: false
  pii: true               # redact PII in output
  prompt_injection: true  # block injection phrasing in input
  pii_action: redact      # flag | redact | block
  injection_action: block # flag | redact | block

tools:                    # sandbox knobs for the file/shell toolkits
  shell_pass_env: false   # pass API keys & other secrets to agent shell commands
  shell_allow_dev_commands: false # opt in to python/git/curl etc. (can escape the workspace jail)
  file_max_read_bytes: 10000000   # refuse file reads larger than this
  file_max_write_bytes: 10000000  # refuse file writes larger than this
  sub_agent_toolkits: null  # allowlist for spawned sub-agents; null = secure default
                            # (file, memory, notepad, web, knowledge, links, clipboard,
                            # comms, a2a, task, alarm, sub_agents -- no shell, git,
                            # delegation, schedule, orchestrator, plugins, or world)

plugins:                  # plugin toolkits from .hive/plugins/ (off by default)
  enabled: false          # set true to hot-load .py Toolkit plugins (full process privileges)
  allowlist: []           # filenames/stems to load; empty = all

retention:                # periodic DB cleanup (off by default)
  enabled: false
  days: 30                # delete terminal rows older than this
  interval_cycles: 100    # run every N heartbeats
  max_runs: 50            # keep at most this many run-log dirs; 0 = unlimited

server:                   # REST API hardening (all off by default)
  api_key: ""             # require X-Hive-Key on data routes (or HIVE_API_KEY)
  cors_origins: []        # allowed CORS origins; empty = none
  session_ttl_hours: 0    # expire idle sessions after N hours; 0 = never

event_log_fsync: false  # fsync every event-log append (crash-durable, slower)
seed: null              # int for a reproducible world RNG; null = system entropy
```

Override with environment variables: `HIVE_HEARTBEAT`, `HIVE_DEFAULT_MODEL`, `HIVE_STARTING_BALANCE`, `HIVE_EVENT_LOG_FSYNC`, `HIVE_SEED`, `HIVE_BUDGET_USD`, `HIVE_BUDGET_TOKENS`.

Manage config from the CLI without editing the file: `hive config` (show), `hive config daemon.heartbeat 30` (set), `hive config --validate` (check).

### Reproducible runs

Set `seed` (or `HIVE_SEED=42 hive start ...`) to make the stochastic world layer --
life-event rolls, luck, and gambling outcomes -- draw from a reproducible stream. Each run
also writes a `manifest.json` (under `logs/runs/<run-id>/`) capturing the hive version, the
seed, the model config, and the spawned agents, so an experiment's setup is fully recorded.
Note: the seed governs the *world* RNG, not LLM outputs, which are not deterministic.
