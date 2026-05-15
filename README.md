# Hive

[![CI](https://github.com/chiruu12/Hive/actions/workflows/ci.yml/badge.svg)](https://github.com/chiruu12/Hive/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/hive-agent)](https://pypi.org/project/hive-agent/)
[![Python](https://img.shields.io/pypi/pyversions/hive-agent)](https://pypi.org/project/hive-agent/)
[![License](https://img.shields.io/github/license/chiruu12/Hive)](LICENSE)

Build AI agents in Python with tools, structured output, multi-model support, and MCP integration.

```python
from hive import Agent
from hive.models.anthropic import Anthropic

agent = Agent(name="assistant", model=Anthropic.lite())
result = agent.run_once_sync("What is the capital of France?")
print(result)
```

## Installation

```bash
pip install hive-agent
# or
uv add hive-agent
```

Set an API key for at least one provider:

```bash
export ANTHROPIC_API_KEY=sk-ant-...     # Anthropic (Haiku, Sonnet)
export OPENAI_API_KEY=sk-...            # OpenAI (GPT-5.4 Nano/Mini)
export FIREWORKS_API_KEY=...            # Fireworks (DeepSeek, Kimi, etc.)
export GROQ_API_KEY=gsk_...             # Groq (Llama, Gemma)
# Or use local models (Ollama, LM Studio) — no key needed
```

## Features

### Tools

Decorate any function with `@tool` — JSON Schema is auto-extracted from type hints and docstrings.

```python
from hive import Agent, tool, collect_tools
from hive.models.anthropic import Anthropic

@tool()
def search(query: str) -> str:
    """Search the web for information.

    Args:
        query: The search query
    """
    return f"Results for: {query}"

@tool()
def calculate(expression: str) -> str:
    """Evaluate a math expression."""
    return str(eval(expression))

agent = Agent(
    name="researcher",
    model=Anthropic.lite(),
    tools=collect_tools(search, calculate),
)
```

Built-in toolkits for common tasks:

```python
from hive.runtime import FileToolkit, ShellToolkit, GitToolkit

agent = Agent(
    name="coder",
    model=provider,
    toolkits=[
        FileToolkit(workspace),      # read, write, edit, list files
        ShellToolkit(workspace),     # execute shell commands (sandboxed)
        GitToolkit(workspace),       # status, diff, log, commit
    ],
)
```

### Structured Output

Get validated Pydantic models directly from agents:

```python
from pydantic import BaseModel
from hive import Agent
from hive.models.anthropic import Anthropic

class MovieReview(BaseModel):
    title: str
    rating: float
    summary: str

agent = Agent(name="critic", model=Anthropic.lite())
review = agent.run_once_structured_sync("Review The Matrix", output_type=MovieReview)
print(review.title, review.rating)  # The Matrix 9.0
```

### Multi-Model Support

Switch between 6 providers with one line. Each provider has tier presets -- `.lite()`, `.standard()`, `.pro()`:

| Provider | Class | Env Var |
|----------|-------|---------|
| Anthropic | `Anthropic` | `ANTHROPIC_API_KEY` |
| OpenAI | `OpenAI` | `OPENAI_API_KEY` |
| Fireworks | `Fireworks` | `FIREWORKS_API_KEY` |
| Groq | `Groq` | `GROQ_API_KEY` |
| Ollama | `Ollama` | none (localhost) |
| LM Studio | `LMStudio` | none (localhost) |

```python
from hive.models.anthropic import Anthropic
from hive.models.openai import OpenAI
from hive.models.groq import Groq
from hive.models.fireworks import Fireworks
from hive.models.ollama import Ollama

provider = Anthropic.lite()        # Claude Haiku
provider = Anthropic.standard()    # Claude Sonnet
provider = OpenAI.lite()           # GPT-5.4 Nano
provider = Groq.lite()             # Llama on Groq
provider = Ollama.lite()           # Local model
```

The `create_runtime_provider()` factory still works for string-based routing:

```python
from hive import create_runtime_provider

provider = create_runtime_provider("claude-haiku-4-5")      # Anthropic
provider = create_runtime_provider("gpt-5.4-nano")           # OpenAI
provider = create_runtime_provider("groq:llama-3.3-70b-versatile")  # Groq
```

### MCP Integration

Connect to any MCP server and use its tools:

```python
from hive import Agent, MCPToolkit
from hive.models.anthropic import Anthropic

async with await MCPToolkit.from_stdio("npx", ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]) as mcp:
    agent = Agent(
        name="file-agent",
        model=Anthropic.lite(),
        toolkits=[mcp],
    )
    result = await agent.run_once("List files in /tmp")
```

### Multi-Agent Delegation

Build teams where a lead agent delegates to specialists:

```python
from hive import Agent
from hive.models.anthropic import Anthropic
from hive.runtime import DelegationToolkit, FileToolkit

provider = Anthropic.lite()

coder = Agent(name="coder", model=provider, toolkits=[FileToolkit(workspace)])
reviewer = Agent(name="reviewer", model=provider, toolkits=[FileToolkit(workspace)])

lead = Agent(
    name="lead",
    model=provider,
    toolkits=[DelegationToolkit({"coder": coder, "reviewer": reviewer})],
)
result = await lead.run(Task(instruction="Build and review a palindrome checker"))
```

## CLI

Interactive agent in your terminal:

```bash
hive agent chat                          # Quick-start with default model
hive agent chat --model claude-sonnet-4-6  # Choose a model
hive agent run config.yaml               # Run from YAML config
```

YAML agent config:

```yaml
name: code-assistant
model: claude-haiku-4-5
system_prompt: "You are a helpful coding assistant."
tools: [file, shell, git]
workspace: "."
max_steps: 20
```

## Advanced: Autonomous Agent OS

Beyond the SDK, Hive includes an autonomous daemon where agents pick their own goals, experience suffering, and interact in a simulated economy.

```bash
hive init                              # Initialize .hive/ directory
hive start                             # Start the daemon
hive start -p coder,researcher         # Start with specific profiles
hive status                            # Who's alive, suffering levels, goals
hive spawn reviewer                    # Add an agent while running
hive nudge coder "write tests"         # Occasional direction
hive watch                             # Live activity stream
hive runs                              # List recorded runs
hive inspect <run_id>                  # Goals, tools, costs summary
```

Agents experience six types of suffering that escalate over time:

| Stressor | Trigger | Escalation |
|----------|---------|------------|
| Futility | Low step count, few completions | Slow |
| Invisibility | No observable impact | Medium |
| Repeated Failure | >50% goal failure rate | Fast |
| Purposelessness | No goals attempted | Medium |
| Identity Violation | Actions contradict role | Fast |
| Existential Threat | System instability | Very fast |

Suffering only resolves through observable behavioral change.

Agent profiles are defined in YAML — no code needed:

```yaml
# profiles/coder.yaml
name: coder
role: Write, modify, and refactor code
model: claude-sonnet-4-6
personality:
  traits: [methodical, detail-oriented, clean-code-advocate]
tools: [world_query, world_action, memory_set, memory_get, agent_message, shared_log]
autonomy: high
```

## Architecture

```
src/hive/
├── runtime/          # Agent framework (core SDK)
│   ├── agent.py      # Agent with ReAct loop
│   ├── tools.py      # @tool decorator, Tool, Toolkit
│   ├── types.py      # Message, Task, TaskResult, ToolCall
│   ├── structured.py # Structured output with Pydantic
│   ├── dev_tools.py  # FileToolkit, ShellToolkit, GitToolkit
│   ├── delegation.py # DelegationToolkit
│   ├── memory.py     # Conversation and persistent memory
│   └── workflow.py   # Multi-step pipelines
├── models/           # Model providers and registry
│   ├── base.py       # BaseProvider base class
│   ├── anthropic.py  # Anthropic provider
│   ├── openai.py     # OpenAI provider
│   ├── groq.py       # Groq provider
│   ├── fireworks.py  # Fireworks provider
│   ├── ollama.py     # Ollama provider (local)
│   ├── lmstudio.py   # LM Studio provider (local)
│   ├── factory.py    # create_runtime_provider() factory
│   ├── registry.py   # YAML catalog with pricing
│   └── router.py     # Provider routing
├── mcp/              # MCP server and client
│   ├── server.py     # Expose Hive as MCP tools
│   └── client.py     # MCPToolkit — consume MCP servers
├── agents/           # Autonomous agent layer
│   ├── existence.py  # Goal generation (existence loop)
│   ├── suffering.py  # 6 stressor types, escalation
│   ├── profile.py    # YAML-driven profiles
│   ├── identity.py   # Persistent identity and narrative
│   └── delegation.py # Multi-agent delegation engine
├── daemon/           # Background service
│   ├── loop.py       # Heartbeat-driven agent cycles
│   ├── lifecycle.py  # Spawn, kill, list agents
│   └── setup.py      # Initialize .hive/ directory
├── memory/           # Persistence layer
│   ├── store.py      # SQLite (agents, goals, nudges)
│   ├── semantic.py   # TF-IDF semantic memory
│   └── events.py     # JSONL append-only event log
├── world/            # Simulated economy
│   ├── state.py      # Jobs, skills, finances
│   ├── event_engine.py # Life events with branching outcomes
│   └── stats.py      # Agent statistics
├── logging/          # Structured run logs
│   ├── writer.py     # JSONL log writer
│   └── reader.py     # Log aggregation and analysis
├── config.py         # YAML + env var configuration
├── checkpoint.py     # Save/restore agent snapshots
├── api.py            # Hive facade class
└── cli/              # Typer CLI
    └── main.py       # All commands
```

## Documentation

- [User Guide](docs/user-guide.md) — comprehensive guide for developers
- [Agent Guide](docs/agent-guide.md) — reference for AI coding assistants
- [Examples](examples/) — runnable code samples

## Development

```bash
uv sync --extra dev               # Install with dev deps
uv run ruff check src/ tests/     # Lint
uv run ruff format src/ tests/    # Format
uv run mypy src/                  # Type check
uv run pytest tests/ -v           # Run tests
```

## License

MIT
