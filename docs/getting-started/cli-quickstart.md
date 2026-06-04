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
| `hive start -p <profiles>` | Start daemon with named profiles |
| `hive watch` | Live TUI dashboard |
| `hive watch --compact` | 2-panel compact dashboard |
| `hive status` | Show agent status, goals, suffering |
| `hive spawn <profile>` | Add an agent |
| `hive kill <agent>` | Terminate an agent |
| `hive nudge <agent> <msg>` | Send direction to an agent |
| `hive doctor` | Health check and diagnostics |
| `hive demo survival` | 3-agent economy simulation |
| `hive demo detective` | Multi-model murder mystery |
| `hive agent chat` | Interactive single-agent with tools |
| `hive agent run <yaml>` | Run agent from YAML config |

## Configuration

All config lives in `.hive/config.yaml`:

```yaml
daemon:
  heartbeat: 10        # seconds between cycles

model:
  default_model: claude-haiku-4-5
  temperature: 0.0

economy:
  enabled: true
  starting_balance: 100.0

suffering:
  threshold_crisis: 0.90
  max_stressors: 5

event_log_fsync: false  # fsync every event-log append (crash-durable, slower)
seed: null              # int for a reproducible world RNG; null = system entropy
```

Override with environment variables: `HIVE_HEARTBEAT`, `HIVE_DEFAULT_MODEL`, `HIVE_STARTING_BALANCE`, `HIVE_EVENT_LOG_FSYNC`, `HIVE_SEED`.

### Reproducible runs

Set `seed` (or `HIVE_SEED=42 hive start ...`) to make the stochastic world layer --
life-event rolls, luck, and gambling outcomes -- draw from a reproducible stream. Each run
also writes a `manifest.json` (under `logs/runs/<run-id>/`) capturing the hive version, the
seed, the model config, and the spawned agents, so an experiment's setup is fully recorded.
Note: the seed governs the *world* RNG, not LLM outputs, which are not deterministic.
