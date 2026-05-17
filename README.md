# Hive

[![CI](https://github.com/chiruu12/Hive/actions/workflows/ci.yml/badge.svg)](https://github.com/chiruu12/Hive/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/hive-agent)](https://pypi.org/project/hive-agent/)
[![Python](https://img.shields.io/pypi/pyversions/hive-agent)](https://pypi.org/project/hive-agent/)
[![License](https://img.shields.io/github/license/chiruu12/Hive)](LICENSE)

An autonomous agent OS that ships as both an **SDK** and a **living simulation**.

`from hive import Agent` gives you an agent that **comes alive** — not stateless function calls, but persistent entities with personality, suffering, and evolution.

<!-- Demo GIF: run demo/record.sh -->

## Quick Start

```bash
pip install hive-agent
```

```python
from hive import Agent, Persona
from hive.models.anthropic import Anthropic

agent = Agent(
    name="coder",
    model=Anthropic.lite(),
    persona=Persona(
        name="The Coder",
        personality=["methodical", "detail-oriented"],
        values=["clean code", "reliability"],
        fears=["shipping bugs"],
        purpose="Build software that works",
        risk_tolerance=0.2,
    ),
)
result = agent.run_once_sync("Write a function that checks if a number is prime")
print(result)
```

Or see it in action:

```bash
hive init && hive demo survival
```

3 agents with different personalities compete in a simulated economy for 30 cycles. Watch them struggle, gamble, philosophize, and suffer.

## Features

### Persona System

Agents have personality, values, fears, and dynamic behavioral state that changes based on suffering:

```python
from hive import Agent, Persona
from hive.models.anthropic import Anthropic

persona = Persona(
    name="The Gambler",
    personality=["bold", "intuitive", "reckless"],
    values=["expected value", "asymmetric upside"],
    fears=["missing out", "becoming too cautious"],
    purpose="Find opportunities others fear",
    risk_tolerance=0.85,   # HIGH — willing to take bigger swings
    social_drive=0.6,
    happiness=0.8,
)

agent = Agent(name="gambler", model=Anthropic.lite(), persona=persona)
```

Suffering mechanically modifies these params each daemon cycle — futility increases risk tolerance, invisibility increases social drive, crisis mode sets extreme values.

### Suffering System

Six stressor types that escalate over time and change agent behavior:

| Stressor | Trigger | Behavioral Effect |
|----------|---------|-------------------|
| Futility | Low completions, stalling | Risk tolerance increases |
| Invisibility | No observable impact | Social drive increases |
| Repeated Failure | >50% goal failure rate | Concentration decreases |
| Purposelessness | No goals attempted | Autonomy increases |
| Identity Violation | Actions contradict role | Risk tolerance decreases |
| Existential Threat | System instability | Extreme parameter shift |

### Tools

Decorate any function with `@tool` — JSON Schema is auto-extracted from type hints:

```python
from hive import Agent, tool, collect_tools
from hive.models.anthropic import Anthropic

@tool()
def search(query: str) -> str:
    """Search the web for information."""
    return f"Results for: {query}"

agent = Agent(
    name="researcher",
    model=Anthropic.lite(),
    tools=collect_tools(search),
)
```

Built-in toolkits: `FileToolkit`, `ShellToolkit`, `GitToolkit`, `WebToolkit`, `NotepadToolkit`, `MemoryToolkit`, `CommsToolkit`, `MCPToolkit`, `DelegationToolkit`, `A2AToolkit`.

### Structured Output

```python
from pydantic import BaseModel
from hive import Agent
from hive.models.anthropic import Anthropic

class Review(BaseModel):
    title: str
    rating: float
    summary: str

agent = Agent(name="critic", model=Anthropic.lite())
review = agent.run_once_structured_sync("Review The Matrix", output_type=Review)
```

### Multi-Model Support

6 providers with tier presets (`.lite()`, `.standard()`, `.pro()`):

| Provider | `.lite()` | `.standard()` | `.pro()` |
|----------|-----------|---------------|----------|
| Anthropic | Haiku | Sonnet | Opus |
| OpenAI | GPT-5.4 Nano | GPT-5.4 Mini | GPT-5.4 |
| Groq | Llama 8B | GPT-OSS 20B | Llama 70B |
| Fireworks | MiniMax | DeepSeek | Kimi |
| Ollama | Local model | Local model | — |
| LM Studio | Auto | — | — |

### Agent-to-Agent Protocol

9 message types, JSONL-backed inbox/outbox, 5 collaboration patterns (Review, Mentor, Debate, Chain, Swarm).

### Sub-Agent Spawning

Parent-child lifecycle with max depth 2, max 5 children, auto-kill at expiry, result relay.

### Agent Journals

Persistent notepads with presets (journal, evolution, tool requests, custom).

### Benchmarking & Export

Compare models on scenarios. Export runs as standalone HTML reports.

## Community Profiles

Dramatic agent personalities for the simulation:

| Profile | Personality | Risk | Social | Key Trait |
|---------|-------------|------|--------|-----------|
| `coder` | Methodical, detail-oriented | 0.3 | 0.3 | Fears shipping bugs |
| `gambler` | Bold, intuitive, reckless | 0.85 | 0.6 | Fears missing out |
| `philosopher` | Contemplative, questions everything | 0.4 | 0.7 | Fears shallow thinking |
| `hustler` | Resourceful, persistent, networking | 0.6 | 0.95 | Fears being idle |
| `oracle` | Wise, deliberate, sees consequences | 0.15 | 0.4 | Fears bad approvals |
| `researcher` | Curious, wide-ranging, thorough | 0.5 | 0.6 | Fears missing info |
| `reviewer` | Analytical, skeptical, fair | 0.2 | 0.5 | Fears missing bugs |
| `tester` | Persistent, edge-case finder | 0.25 | 0.4 | Fears false confidence |

## CLI

```bash
# SDK usage
hive agent chat                        # Interactive agent with tools
hive agent run config.yaml             # Run from YAML config

# Demos
hive demo survival                     # 3 agents, 30 cycles, economy on
hive demo detective                    # Multi-model murder mystery

# Autonomous OS
hive init                              # Initialize .hive/ directory
hive start -p coder,gambler,philosopher # Start with specific profiles
hive watch                             # Live 4-panel TUI dashboard
hive watch --compact                   # 2-panel for small terminals
hive status                            # Who's alive, goals, suffering
hive nudge coder "write tests"         # Occasional direction
hive doctor                            # Health check
```

## Architecture

```
src/hive/
├── runtime/        # Agent framework (Agent, Instructions, Persona, ReAct loop)
├── tools/          # Toolkits (file, shell, git, web, notepad, memory, comms, A2A)
├── models/         # Providers (Anthropic, OpenAI, Groq, Fireworks, Ollama, LMStudio)
├── agents/         # Autonomy (existence loop, suffering, identity, profiles)
├── daemon/         # Background service (heartbeat loop, lifecycle)
├── interactions/   # A2A protocol, collaboration patterns
├── memory/         # SQLite store, semantic memory, event log
├── world/          # Economy simulation (jobs, money, skills, events)
├── demos/          # Built-in demos (survival, detective)
├── benchmark/      # Model comparison scenarios
├── export/         # HTML report generation
├── logging/        # Structured JSONL run logs
├── mcp/            # MCP server and client
├── cli/            # Typer CLI
├── config.py       # YAML + env var configuration
├── checkpoint.py   # Agent state snapshots
└── api.py          # Programmatic Hive facade
```

## Documentation

- [User Guide](docs/user-guide.md) — comprehensive developer guide
- [Agent Guide](docs/agent-guide.md) — reference for AI coding assistants
- [Examples](examples/) — 15 runnable code samples
- [Contributing](CONTRIBUTING.md) — how to add toolkits, providers, profiles
- [Changelog](CHANGELOG.md) — version history

## Development

```bash
git clone https://github.com/chiruu12/Hive.git && cd Hive
uv sync
uv run pytest                    # Run tests
uv run ruff check src tests      # Lint
uv run ruff format src tests     # Format
```

## License

MIT
