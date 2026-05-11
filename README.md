# Hive

**Autonomous agent OS.** Start the hive, watch AI agents come alive. They pick their own goals, suffer when they fail, interact with each other, and make decisions in a mini economy. You observe and occasionally nudge.

```bash
pip install hive-agent
hive init
hive start
```

Not a task runner. An ant farm.

## What Happens When You Start

1. Agents spawn from YAML profiles (coder, reviewer, researcher, tester, oracle)
2. Each agent enters an **existence loop** — evaluating its situation, peers, and suffering
3. The agent autonomously generates a goal based on context
4. A **plan-execute-substitute** engine breaks the goal into tool calls
5. Results chain into the next step. Failures trigger replanning.
6. After completion, the cycle repeats — new goal, new plan, new execution
7. **Suffering escalates** when things go wrong. Agents must address root causes to resolve it.

## CLI

```bash
hive init                          # Initialize .hive/ directory
hive start                         # Start the daemon — agents come alive
hive start -p coder,researcher     # Start with specific profiles
hive start -b 15                   # Custom heartbeat interval (seconds)

hive status                        # Who's alive, suffering levels, current goals
hive spawn reviewer                # Add a new agent while running
hive nudge coder "write tests"     # Give occasional direction
hive kill coder-abc123             # Remove an agent
hive watch                         # Live stream of agent activity

hive runs                          # List all recorded runs
hive inspect <run_id>              # Detailed summary: goals, tools, costs
hive models                        # Show available model providers
hive replay <session_id>           # Step-by-step replay of a session
```

## Architecture

```
src/hive/
├── agents/           # Agent profiles, state, and goal generation
│   ├── existence.py  # Autonomous goal generation (existence loop)
│   ├── suffering.py  # 6 stressor types, escalation, resolution
│   ├── profile.py    # YAML-driven agent config
│   └── state.py      # Runtime state model
├── runtime/          # Standalone agent framework
│   ├── agent.py      # ReAct loop (observe → think → act)
│   ├── tools.py      # Tool and Toolkit with JSON Schema extraction
│   ├── toolkits.py   # Built-in toolkits (world, memory, comms)
│   ├── providers.py  # Anthropic and OpenAI provider implementations
│   ├── memory.py     # Conversation and persistent memory
│   ├── types.py      # Message, Task, TaskResult, ToolCall
│   ├── bridge.py     # DaemonAgentAdapter for daemon integration
│   └── workflow.py   # Multi-step agent pipelines
├── daemon/           # Background service
│   ├── loop.py       # Heartbeat drives all agents on a cycle
│   ├── lifecycle.py  # Spawn, kill, list agents
│   └── setup.py      # Initialize .hive/ directory
├── models/           # Model registry and routing
│   ├── registry.py   # YAML model catalog with pricing
│   └── router.py     # Provider factory and model detection
├── interactions/     # Multi-agent interaction patterns
│   ├── exchange.py   # ExchangeRunner (participant-based)
│   ├── runner.py     # ScenarioRunner (YAML-driven scenarios)
│   └── patterns/     # Round-table, pairs, freeform
├── memory/           # Persistence
│   ├── store.py      # SQLite (agents, goals, nudges, sessions)
│   ├── semantic.py   # TF-IDF semantic memory with JSONL storage
│   └── events.py     # JSONL append-only event log
├── context.py        # ExecutionContext (injected state for tools)
└── logging/          # Structured run logs
    ├── models.py     # RunLog, CycleLog, GoalLog, DecisionLog, ToolLog
    ├── writer.py     # Writes to logs/runs/{id}/agents/{aid}/*.jsonl
    └── reader.py     # Loads and aggregates for analysis
```

## Suffering System

Agents experience six types of suffering that escalate over time if unresolved:

| Stressor | Trigger | Escalation |
|----------|---------|------------|
| Futility | Low step count, few completions | Slow (0.025/day) |
| Invisibility | No observable impact | Medium (0.030/day) |
| Repeated Failure | >50% goal failure rate | Fast (0.040/day) |
| Purposelessness | No goals attempted | Medium (0.035/day) |
| Identity Violation | Actions contradict role | Fast (0.060/day) |
| Existential Threat | System instability | Very fast (0.070/day) |

**Thresholds:** 0.35 appears in prompts → 0.55 constrains goals → 0.75 forces introspection → 0.90 crisis mode

Suffering only resolves through observable behavioral change — not by deciding to feel better.

## Agent Profiles

Agents are defined in YAML. No code needed.

```yaml
# profiles/coder.yaml
name: coder
role: Write, modify, and refactor code
model: claude-sonnet-4-6
personality:
  traits: [methodical, detail-oriented, clean-code-advocate]
  style: concise and precise
tools: [world_query, world_action, memory_set, memory_get, agent_message, shared_log]
autonomy: high
max_steps: 20
```

Five presets included: `coder`, `reviewer`, `researcher`, `tester`, `oracle`.

## Structured Logging

Every run is recorded in `logs/runs/{run_id}/`:

```
logs/runs/run-20260505-183000-abc123/
├── run.json                           # Run metadata
├── cycles/cycle_0001.jsonl            # Per-cycle: agents active, goals, crisis
└── agents/coder-abc123/
    ├── goals.jsonl                    # Full goal lifecycle with reasoning
    ├── decisions.jsonl                # Every LLM call with full response + tokens + cost
    ├── tools.jsonl                    # Every tool call with untruncated I/O + timing
    └── suffering.jsonl                # Suffering snapshots per cycle
```

Use `hive inspect <run_id>` for a summary, or feed logs to an analysis agent.

## Tech Stack

- **Python 3.11+**, async throughout
- **Claude Code CLI** as LLM backend (no API key needed — uses CLI auth)
- **SQLite** via aiosqlite for state
- **JSONL** for append-only event logs
- **Typer + Rich** for CLI
- **Pydantic** for all data models

## Development

```bash
uv sync --extra dev               # Install with dev deps
uv run pytest                     # Run tests
uv run ruff check src/            # Lint
uv run ruff format src/           # Format
uv run mypy src/                  # Type check
```

## License

MIT
