# hive-agent Developer Guide

A comprehensive guide to building AI agents with the `hive-agent` Python SDK. This framework provides a ReAct-loop agent runtime with multi-model support, tool use, structured output, multi-agent delegation, and MCP integration.

---

## Table of Contents

- [Installation](#installation)
- [Quickstart](#quickstart)
- [Core Concepts](#core-concepts)
- [Agent](#agent)
  - [Creating an Agent](#creating-an-agent)
  - [Running Tasks (ReAct Loop)](#running-tasks-react-loop)
  - [Single Request-Response](#single-request-response)
  - [Structured Output](#structured-output)
  - [Budget Limits](#budget-limits)
- [Model Providers](#model-providers)
  - [Provider Factory](#provider-factory)
  - [Direct Provider Construction](#direct-provider-construction)
  - [Local Models (Ollama, LM Studio)](#local-models-ollama-lm-studio)
- [Tool System](#tool-system)
  - [The @tool() Decorator](#the-tool-decorator)
  - [Standalone Functions as Tools](#standalone-functions-as-tools)
  - [Custom Toolkits](#custom-toolkits)
- [Built-in Toolkits](#built-in-toolkits)
  - [FileToolkit](#filetoolkit)
  - [ShellToolkit](#shelltoolkit)
  - [GitToolkit](#gittoolkit)
  - [DelegationToolkit](#delegationtoolkit)
- [MCP Integration](#mcp-integration)
- [Multi-Agent Patterns](#multi-agent-patterns)
  - [Delegation](#delegation)
  - [Workflows (Pipelines)](#workflows-pipelines)
- [Persistent Memory](#persistent-memory)
- [Configuration](#configuration)
  - [API Keys (.env)](#api-keys-env)
  - [Model Registry (models.yaml)](#model-registry-modelsyaml)
- [Plugin System](#plugin-system)
- [CLI Usage](#cli-usage)
- [API Reference Summary](#api-reference-summary)

---

## Installation

```bash
pip install hive-agent
```

Requires Python 3.11 or later. The package installs with support for both Anthropic and OpenAI providers out of the box.

For development:

```bash
pip install hive-agent[dev]
```

This adds pytest, pytest-asyncio, ruff, and mypy.

---

## Quickstart

Create a `.env` file with your API key, then run your first agent in under 10 lines:

```python
import asyncio
from hive import Agent, Task, create_runtime_provider

async def main():
    provider = create_runtime_provider("claude-haiku-4-5")
    agent = Agent(name="assistant", model=provider)
    result = await agent.run(Task(instruction="What is the capital of France?"))
    print(result.output)

asyncio.run(main())
```

Or use the synchronous one-shot API for scripts where you do not need the full ReAct loop:

```python
from hive import Agent, create_runtime_provider

provider = create_runtime_provider("claude-haiku-4-5")
agent = Agent(name="assistant", model=provider)
answer = agent.run_once_sync("What is the capital of France?")
print(answer)
```

---

## Core Concepts

The SDK is organized around a few key abstractions:

| Concept | Description |
|---------|-------------|
| **Agent** | The central class. Runs a ReAct loop: prompt the model, execute tool calls, repeat until done. |
| **Task** | A unit of work with an instruction, optional context, and a step limit. |
| **TaskResult** | The outcome of running a task: status, output text, step/tool counts, timing. |
| **Tool** | A callable function with metadata and JSON Schema, invocable by the model. |
| **Toolkit** | A group of related tools. Subclass it and decorate methods with `@tool()`. |
| **RuntimeProvider** | Protocol for LLM backends. Route between Anthropic, OpenAI, Fireworks, Groq, Ollama, LM Studio. |
| **Workflow** | A pipeline of Steps that chain agents together, passing context between them. |

---

## Agent

### Creating an Agent

```python
from hive import Agent, create_runtime_provider
from hive.runtime import FileToolkit, ShellToolkit

provider = create_runtime_provider("claude-haiku-4-5")

agent = Agent(
    name="coder",
    model=provider,
    system_prompt="You are an expert Python developer.",
    toolkits=[
        FileToolkit(workspace=Path("./project")),
        ShellToolkit(workspace=Path("./project")),
    ],
    max_steps=25,
    temperature=0.0,
    max_cost_usd=1.00,
    max_tokens=100_000,
)
```

**Constructor parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `name` | `str` | required | Human-readable name for the agent. |
| `model` | `RuntimeProvider` | required | The LLM provider to use. |
| `system_prompt` | `str` | `""` | System message prepended to every conversation. |
| `toolkits` | `list[Toolkit] \| None` | `None` | Toolkit instances whose tools the agent can call. |
| `tools` | `list[Tool] \| None` | `None` | Individual Tool objects (in addition to toolkits). |
| `memory` | `PersistentMemory \| None` | `None` | Cross-session memory for context recall. |
| `max_steps` | `int` | `25` | Maximum ReAct loop iterations before stopping. |
| `temperature` | `float` | `0.0` | Sampling temperature for the model. |
| `max_cost_usd` | `float` | `0.0` | Cost budget in USD. 0 means unlimited. |
| `max_tokens` | `int` | `0` | Max tokens per generation. 0 means default (4096). |

### Running Tasks (ReAct Loop)

The `run()` method executes a multi-step ReAct loop. The agent reasons, calls tools, observes results, and repeats until it produces a final text response or hits the step limit.

```python
import asyncio
from pathlib import Path
from hive import Agent, Task, create_runtime_provider
from hive.runtime import FileToolkit

async def main():
    provider = create_runtime_provider("claude-haiku-4-5")
    agent = Agent(
        name="analyst",
        model=provider,
        system_prompt="You are a code analyst.",
        toolkits=[FileToolkit(workspace=Path("./repo"))],
    )

    task = Task(
        instruction="Read main.py and summarize what it does.",
        context={"language": "python"},
        max_steps=10,
    )
    result = await agent.run(task)

    print(f"Status: {result.status}")        # "completed", "failed", or "max_steps"
    print(f"Steps: {result.steps_taken}")
    print(f"Tool calls: {result.tool_calls_made}")
    print(f"Duration: {result.duration_seconds:.1f}s")
    print(f"Output:\n{result.output}")

asyncio.run(main())
```

**Task fields:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `instruction` | `str` | required | What the agent should do. |
| `id` | `str` | auto-generated | Unique task identifier (`task-<hex>`). |
| `context` | `dict[str, Any]` | `{}` | Key-value pairs appended to the instruction. |
| `max_steps` | `int` | `25` | Override the agent's default step limit for this task. |

**TaskResult fields:**

| Field | Type | Description |
|-------|------|-------------|
| `task_id` | `str` | Matches the Task's id. |
| `status` | `TaskStatus` | One of: `PENDING`, `RUNNING`, `COMPLETED`, `FAILED`, `MAX_STEPS`. |
| `output` | `str` | The agent's final text output. |
| `steps_taken` | `int` | Number of ReAct iterations executed. |
| `tool_calls_made` | `int` | Total tool invocations across all steps. |
| `error` | `str \| None` | Error message if status is `FAILED`. |
| `duration_seconds` | `float` | Wall-clock time for the entire run. |

### Single Request-Response

For simple tasks that do not need multi-step reasoning, use `run_once()`. It sends one message, handles a single round of tool calls if needed, and returns the text response directly.

```python
import asyncio
from hive import Agent, create_runtime_provider

async def main():
    provider = create_runtime_provider("claude-haiku-4-5")
    agent = Agent(name="helper", model=provider)

    # Async version
    answer = await agent.run_once("Explain the GIL in Python in two sentences.")
    print(answer)

    # With extra context
    answer = await agent.run_once(
        "Summarize the error.",
        context="Error: FileNotFoundError: No such file 'data.csv'",
    )
    print(answer)

asyncio.run(main())
```

**Synchronous wrappers** work anywhere, including inside scripts that do not have an async event loop:

```python
from hive import Agent, create_runtime_provider

provider = create_runtime_provider("claude-haiku-4-5")
agent = Agent(name="helper", model=provider)

# No asyncio.run needed
answer = agent.run_once_sync("Explain the GIL in Python in two sentences.")
print(answer)
```

**All run_once variants:**

| Method | Returns | Async |
|--------|---------|-------|
| `run_once(message, context?)` | `str` | Yes |
| `run_once_sync(message, context?)` | `str` | No |
| `run_once_structured(message, output_type, context?)` | `T` | Yes |
| `run_once_structured_sync(message, output_type, context?)` | `T` | No |

### Structured Output

Return validated Pydantic models instead of raw text. The SDK uses native provider support (Anthropic `tool_choice`, OpenAI `json_schema` response format) with automatic fallback for local models that lack structured output support.

**Single request-response:**

```python
import asyncio
from pydantic import BaseModel
from hive import Agent, create_runtime_provider

class Sentiment(BaseModel):
    label: str
    confidence: float
    reasoning: str

async def main():
    provider = create_runtime_provider("claude-haiku-4-5")
    agent = Agent(name="classifier", model=provider)

    result = await agent.run_once_structured(
        "Analyze sentiment: 'This product is amazing!'",
        output_type=Sentiment,
    )
    print(result.label)        # "positive"
    print(result.confidence)   # 0.95
    print(result.reasoning)    # "The word 'amazing' indicates..."

asyncio.run(main())
```

**With the full ReAct loop** (via `run_structured`):

```python
import asyncio
from pydantic import BaseModel
from hive import Agent, Task, create_runtime_provider

class CodeReview(BaseModel):
    summary: str
    issues: list[str]
    score: int

async def main():
    provider = create_runtime_provider("claude-sonnet-4-6")
    agent = Agent(name="reviewer", model=provider)

    task = Task(instruction="Review this code for quality issues: def f(x): return x+1")
    result = await agent.run_structured(task, output_type=CodeReview)

    print(f"Status: {result.status}")
    print(f"Score: {result.parsed.score}")
    for issue in result.parsed.issues:
        print(f"  - {issue}")

asyncio.run(main())
```

The `StructuredTaskResult` extends `TaskResult` with a `parsed: T` field containing the validated Pydantic model.

**Sync version:**

```python
from pydantic import BaseModel
from hive import Agent, create_runtime_provider

class City(BaseModel):
    name: str
    country: str
    population: int

provider = create_runtime_provider("claude-haiku-4-5")
agent = Agent(name="geo", model=provider)

city = agent.run_once_structured_sync("Tell me about Tokyo.", output_type=City)
print(f"{city.name}, {city.country} - pop. {city.population:,}")
```

### Budget Limits

Protect against runaway costs with per-run budgets. The agent checks after every model call and stops with a `FAILED` status if either limit is exceeded.

```python
agent = Agent(
    name="careful",
    model=provider,
    max_cost_usd=0.50,     # Stop if accumulated cost reaches $0.50
    max_tokens=50_000,      # Stop if total tokens (input + output) reach 50k
)
```

When a budget is exceeded, the `TaskResult` will have `status=FAILED` and the `error` field will explain which limit was hit.

---

## Model Providers

### Provider Factory

The `create_runtime_provider()` factory routes model names to the correct provider class:

```python
from hive import create_runtime_provider

# Anthropic (requires ANTHROPIC_API_KEY in .env or environment)
claude_haiku = create_runtime_provider("claude-haiku-4-5")
claude_sonnet = create_runtime_provider("claude-sonnet-4-6")

# OpenAI (requires OPENAI_API_KEY)
gpt_nano = create_runtime_provider("gpt-5.4-nano")
gpt_mini = create_runtime_provider("gpt-5.4-mini")

# Fireworks (requires FIREWORKS_API_KEY)
fireworks = create_runtime_provider("fireworks:accounts/fireworks/models/llama-v3-70b")

# Groq (requires GROQ_API_KEY)
groq = create_runtime_provider("groq:llama-3.1-70b-versatile")

# Ollama (no key needed, localhost:11434)
ollama = create_runtime_provider("ollama:llama3.1")

# LM Studio (no key needed, localhost:1234)
lmstudio = create_runtime_provider("lmstudio:qwen2.5-coder-7b")
```

**Routing rules:**

| Model name pattern | Provider | Required env var |
|-------------------|----------|-----------------|
| Contains `"claude"` | `AnthropicRuntimeProvider` | `ANTHROPIC_API_KEY` |
| Starts with `"gpt-"` | `OpenAIRuntimeProvider` | `OPENAI_API_KEY` |
| Starts with `"fireworks:"` | `OpenAIRuntimeProvider` (Fireworks URL) | `FIREWORKS_API_KEY` |
| Starts with `"groq:"` | `OpenAIRuntimeProvider` (Groq URL) | `GROQ_API_KEY` |
| Starts with `"ollama:"` | `OpenAIRuntimeProvider` (localhost:11434) | None |
| Starts with `"lmstudio:"` | `OpenAIRuntimeProvider` (localhost:1234) | None |
| Anything else | `OpenAIRuntimeProvider` (Ollama fallback) | None |

### Direct Provider Construction

For full control, construct providers directly:

```python
from hive.runtime.providers import AnthropicRuntimeProvider, OpenAIRuntimeProvider

# Anthropic with explicit key
provider = AnthropicRuntimeProvider(
    model="claude-haiku-4-5",
    api_key="sk-ant-...",
)

# OpenAI with explicit key
provider = OpenAIRuntimeProvider(
    model="gpt-5.4-nano",
    api_key="sk-...",
)

# Any OpenAI-compatible endpoint
provider = OpenAIRuntimeProvider(
    model="my-model",
    api_key="my-key",
    base_url="https://my-provider.com/v1",
)
```

### Local Models (Ollama, LM Studio)

Local providers check server health before use. The `available` property probes the `/models` endpoint and caches the result for 30 seconds.

```python
provider = create_runtime_provider("ollama:llama3.1")

if provider.available:
    agent = Agent(name="local", model=provider)
    print(agent.run_once_sync("Hello!"))
else:
    print("Ollama server not running. Start with: ollama serve")
```

Structured output automatically falls back to prompt-based JSON extraction for local models that lack native `json_schema` support.

---

## Tool System

### The @tool() Decorator

Mark any function or method as a tool. The decorator extracts JSON Schema from type hints and descriptions from the docstring. The model sees these schemas when deciding which tools to call.

```python
from hive.runtime.tools import tool

@tool()
def calculate(expression: str) -> str:
    """Evaluate a mathematical expression.

    Args:
        expression: A Python math expression like '2 + 2' or 'math.sqrt(16)'.
    """
    import math
    try:
        result = eval(expression, {"math": math, "__builtins__": {}})
        return str(result)
    except Exception as e:
        return f"Error: {e}"
```

**How schema extraction works:**

- The function name becomes the tool name (or pass `name="custom_name"` to override).
- The first paragraph of the docstring becomes the tool description (or pass `description="..."` to override).
- Parameter types are converted to JSON Schema (`str` -> `"string"`, `int` -> `"integer"`, `list[str]` -> array of strings, etc.).
- Parameter descriptions are extracted from the `Args:` section of the docstring (Google style).
- Parameters with defaults are marked as optional in the schema; those without defaults are required.
- `Optional[T]` (or `T | None`) parameters are always optional.
- Pydantic models and dataclasses used as parameter types are inlined as JSON Schema objects.

**Supported type mappings:**

| Python type | JSON Schema |
|------------|-------------|
| `str` | `{"type": "string"}` |
| `int` | `{"type": "integer"}` |
| `float` | `{"type": "number"}` |
| `bool` | `{"type": "boolean"}` |
| `dict` | `{"type": "object"}` |
| `list[str]` | `{"type": "array", "items": {"type": "string"}}` |
| `Literal["a", "b"]` | `{"type": "string", "enum": ["a", "b"]}` |
| Pydantic `BaseModel` | Inlined object schema from `model_json_schema()` |
| `dataclass` | Object schema from field type hints |

### Standalone Functions as Tools

Convert plain functions to `Tool` objects with `make_tool()`, or batch-convert with `collect_tools()`:

```python
from hive import make_tool, collect_tools

def get_weather(city: str) -> str:
    """Get the current weather for a city.

    Args:
        city: Name of the city.
    """
    return f"Sunny, 72F in {city}"

def get_time(timezone: str = "UTC") -> str:
    """Get the current time in a timezone.

    Args:
        timezone: IANA timezone name.
    """
    from datetime import datetime, timezone as tz
    return datetime.now(tz.utc).isoformat()

# Single function
weather_tool = make_tool(get_weather)

# Multiple functions at once
tools = collect_tools(get_weather, get_time)

# Pass to an agent
agent = Agent(name="helper", model=provider, tools=tools)
```

### Custom Toolkits

Group related tools by subclassing `Toolkit`. Each `@tool()`-decorated method is auto-discovered.

```python
from hive.runtime.tools import Toolkit, tool

class WeatherToolkit(Toolkit):
    """Tools for weather information."""

    def __init__(self, api_key: str):
        self._api_key = api_key

    @tool()
    def get_forecast(self, city: str, days: int = 3) -> str:
        """Get a weather forecast for a city.

        Args:
            city: The city name.
            days: Number of days to forecast (1-7).
        """
        # Use self._api_key to call a real API
        return f"Forecast for {city}: sunny for {days} days"

    @tool()
    def get_alerts(self, region: str) -> str:
        """Get active weather alerts for a region.

        Args:
            region: State or region code (e.g. 'CA', 'TX').
        """
        return f"No active alerts for {region}"

# Use it
toolkit = WeatherToolkit(api_key="...")
agent = Agent(name="weather-bot", model=provider, toolkits=[toolkit])
```

Async methods are fully supported -- just use `async def`:

```python
class AsyncToolkit(Toolkit):
    @tool()
    async def fetch_data(self, url: str) -> str:
        """Fetch data from a URL.

        Args:
            url: The URL to fetch.
        """
        import httpx
        async with httpx.AsyncClient() as client:
            resp = await client.get(url)
            return resp.text[:2000]
```

---

## Built-in Toolkits

Import all built-in toolkits from `hive.runtime`:

```python
from hive.runtime import FileToolkit, ShellToolkit, GitToolkit, DelegationToolkit
```

### FileToolkit

Sandboxed file system access scoped to a workspace directory. All paths are resolved relative to the workspace; any attempt to escape via `../` raises `PermissionError`.

```python
from pathlib import Path
from hive.runtime import FileToolkit

files = FileToolkit(workspace=Path("./my-project"))
```

**Tools provided:**

| Tool | Description |
|------|-------------|
| `file_read(path, offset=0, limit=500)` | Read a file with line numbers. `offset` and `limit` control the window. |
| `file_write(path, content)` | Write content to a file. Creates parent directories as needed. |
| `file_edit(path, old_text, new_text)` | Replace an exact string in a file. Fails if the match is ambiguous (appears more than once). |
| `list_dir(path=".", max_depth=2)` | List files and directories as a tree. |

### ShellToolkit

Sandboxed shell command execution. By default, only a safe allowlist of commands is permitted.

```python
from pathlib import Path
from hive.runtime import ShellToolkit

# Restricted mode (default) -- only allowlisted commands
shell = ShellToolkit(workspace=Path("./my-project"), timeout=30, restrict=True)

# Unrestricted mode -- any command allowed (use with caution)
shell = ShellToolkit(workspace=Path("./my-project"), restrict=False)
```

**Constructor parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `workspace` | `Path` | required | Working directory for all commands. |
| `timeout` | `int` | `30` | Maximum seconds a command can run. |
| `restrict` | `bool` | `True` | Enforce the command allowlist. |

**Default allowlist includes:** `ls`, `cat`, `head`, `tail`, `grep`, `find`, `python`, `python3`, `pip`, `uv`, `node`, `npm`, `npx`, `git`, `ruff`, `mypy`, `pytest`, `cargo`, `go`, `make`, `curl`, `jq`, and more.

**Tool provided:**

| Tool | Description |
|------|-------------|
| `shell_exec(command)` | Execute a shell command and return stdout, stderr, and exit code. Output is truncated to 5000 chars. |

### GitToolkit

Git operations within a workspace directory.

```python
from pathlib import Path
from hive.runtime import GitToolkit

git = GitToolkit(workspace=Path("./my-repo"))
```

**Tools provided:**

| Tool | Description |
|------|-------------|
| `git_status()` | Show working tree status (`--short`). |
| `git_diff(staged=False)` | Show changes. Set `staged=True` for cached diff. |
| `git_log(count=10)` | Show recent commit history (`--oneline`). |
| `git_add(path=".")` | Stage files for commit. |
| `git_commit(message)` | Create a commit. |
| `git_init()` | Initialize a new repository. |

### DelegationToolkit

Let one agent delegate tasks to other agents. The delegating agent can invoke sub-agents by name and receive their results.

```python
from hive.runtime import DelegationToolkit

researcher = Agent(name="researcher", model=provider, system_prompt="You research topics.")
coder = Agent(name="coder", model=provider, system_prompt="You write Python code.")

delegation = DelegationToolkit(agents={
    "researcher": researcher,
    "coder": coder,
})

lead = Agent(
    name="lead",
    model=provider,
    system_prompt="You are a tech lead. Delegate research and coding tasks.",
    toolkits=[delegation],
)
```

**Tools provided:**

| Tool | Description |
|------|-------------|
| `delegate_task(agent_name, task)` | Delegate a task to another agent and get their result. |
| `list_agents()` | List all available agents for delegation. |

---

## MCP Integration

Connect to any MCP (Model Context Protocol) server and use its tools as native Hive tools. The `MCPToolkit` wraps MCP server tools as standard `Tool` objects.

```python
import asyncio
from hive import Agent, Task, MCPToolkit, create_runtime_provider

async def main():
    provider = create_runtime_provider("claude-haiku-4-5")

    # Connect to an MCP server via stdio
    async with await MCPToolkit.from_stdio(
        "npx", ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
    ) as mcp:
        print(f"Connected: {mcp.tool_count} tools from {mcp.server_name}")

        agent = Agent(
            name="fs-agent",
            model=provider,
            toolkits=[mcp],
        )
        result = await agent.run(Task(instruction="List all files in /tmp"))
        print(result.output)

asyncio.run(main())
```

**Connecting from a config dict:**

```python
mcp = await MCPToolkit.from_config({
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-memory"],
    "env": {"MEMORY_DIR": "/tmp/memory"},
})
```

**Manual lifecycle (without context manager):**

```python
mcp = await MCPToolkit.from_stdio("npx", ["-y", "some-server"])
try:
    agent = Agent(name="a", model=provider, toolkits=[mcp])
    result = await agent.run(Task(instruction="Do something"))
finally:
    await mcp.close()
```

**`from_stdio` parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `command` | `str` | required | The executable to run. |
| `args` | `list[str] \| None` | `None` | Command-line arguments. |
| `env` | `dict[str, str] \| None` | `None` | Environment variables for the subprocess. |
| `cwd` | `str \| Path \| None` | `None` | Working directory for the subprocess. |

---

## Multi-Agent Patterns

### Delegation

A lead agent delegates subtasks to specialist agents at runtime via tool calls:

```python
import asyncio
from pathlib import Path
from hive import Agent, Task, create_runtime_provider
from hive.runtime import FileToolkit, ShellToolkit, DelegationToolkit

async def main():
    provider = create_runtime_provider("claude-sonnet-4-6")
    workspace = Path("./project")

    researcher = Agent(
        name="researcher",
        model=create_runtime_provider("claude-haiku-4-5"),
        system_prompt="You research topics and provide detailed summaries.",
    )

    coder = Agent(
        name="coder",
        model=provider,
        system_prompt="You write clean, tested Python code.",
        toolkits=[
            FileToolkit(workspace=workspace),
            ShellToolkit(workspace=workspace),
        ],
    )

    lead = Agent(
        name="lead",
        model=provider,
        system_prompt=(
            "You are a tech lead. Break tasks into research and coding subtasks. "
            "Delegate to the researcher for information gathering and the coder "
            "for implementation."
        ),
        toolkits=[DelegationToolkit(agents={"researcher": researcher, "coder": coder})],
    )

    result = await lead.run(Task(
        instruction="Research best practices for Python CLI tools, then create a simple CLI app."
    ))
    print(result.output)

asyncio.run(main())
```

### Workflows (Pipelines)

Chain agents into sequential pipelines where each step's output feeds into the next:

```python
import asyncio
from hive import Agent, create_runtime_provider
from hive.runtime import Step, Workflow

async def main():
    haiku = create_runtime_provider("claude-haiku-4-5")

    planner = Agent(name="planner", model=haiku, system_prompt="You create project plans.")
    writer = Agent(name="writer", model=haiku, system_prompt="You write code based on plans.")
    reviewer = Agent(name="reviewer", model=haiku, system_prompt="You review code for quality.")

    workflow = Workflow(
        name="build-feature",
        steps=[
            Step(
                name="plan",
                agent=planner,
                instruction="Create a plan for: {feature_description}",
                output_key="plan",
            ),
            Step(
                name="implement",
                agent=writer,
                instruction="Implement this plan:\n{plan}",
                output_key="code",
            ),
            Step(
                name="review",
                agent=reviewer,
                instruction="Review this code:\n{code}",
                output_key="review",
            ),
        ],
    )

    result = await workflow.run({"feature_description": "A URL shortener module"})
    print("Plan:", result["plan"][:200])
    print("Review:", result["review"][:200])

asyncio.run(main())
```

**Step fields:**

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | Identifier for this step. |
| `agent` | `Agent` | The agent that executes this step. |
| `instruction` | `str` | Template string with `{key}` placeholders filled from context. |
| `fn` | `Callable \| None` | Alternative: an async function instead of an agent. |
| `output_key` | `str` | Key under which the step's output is stored in the context dict. |

Steps can use either an `agent` or a custom `fn` (async callable). The instruction string supports Python `str.format_map` placeholders that resolve from the accumulated context.

---

## Persistent Memory

Give agents cross-session memory that persists between runs. The `PersistentMemory` class wraps a semantic memory store backed by SQLite.

```python
import asyncio
from pathlib import Path
from hive import Agent, Task, create_runtime_provider
from hive.runtime import PersistentMemory

async def main():
    provider = create_runtime_provider("claude-haiku-4-5")
    memory = PersistentMemory(agent_name="assistant", hive_dir=Path("./.hive"))

    agent = Agent(
        name="assistant",
        model=provider,
        system_prompt="You are a helpful assistant with long-term memory.",
        memory=memory,
    )

    # First run -- the agent stores context
    await agent.run(Task(instruction="My favorite color is blue. Remember this."))

    # Later run -- the agent recalls relevant memories automatically
    result = await agent.run(Task(instruction="What is my favorite color?"))
    print(result.output)  # Should recall "blue"

asyncio.run(main())
```

When an agent with `PersistentMemory` starts a task, it automatically recalls up to 3 relevant memories based on semantic similarity to the current instruction and injects them as system context.

**PersistentMemory methods:**

| Method | Description |
|--------|-------------|
| `store(content, metadata?)` | Store a memory entry. Returns the memory ID. |
| `recall(query, limit=5)` | Retrieve relevant memories by similarity search. |
| `clear()` | Delete all stored memories for this agent. |

---

## Configuration

### API Keys (.env)

Create a `.env` file in your project root (or any parent directory):

```env
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
FIREWORKS_API_KEY=...
GROQ_API_KEY=gsk_...
```

The SDK loads `.env` values using `python-dotenv` but does **not** inject them into `os.environ`. Keys are read via `get_env()`, which checks the `.env` file first, then falls back to environment variables.

```python
from hive.config import get_env

# Reads from .env file first, then os.environ
key = get_env("ANTHROPIC_API_KEY")
custom = get_env("MY_CUSTOM_VAR", default="fallback")
```

### Model Registry (models.yaml)

The `models.yaml` file defines the model catalog and cost estimation data. It is bundled with the package and used by `estimate_cost()` to calculate per-call costs for budget tracking.

### HiveConfig

For daemon and advanced settings, use `HiveConfig`:

```python
from hive import HiveConfig, load_config
from pathlib import Path

# Load from .hive/config.yaml with env var overrides
config = load_config(hive_dir=Path("./.hive"))

# Access settings
print(config.model.default_model)       # "claude-haiku-4-5"
print(config.economy.starting_balance)  # 100.0
print(config.daemon.heartbeat)          # 10
```

**Environment variable overrides:**

| Env var | Config path | Type |
|---------|------------|------|
| `HIVE_DEFAULT_MODEL` | `model.default_model` | `str` |
| `HIVE_HEARTBEAT` | `daemon.heartbeat` | `int` |
| `HIVE_MAX_RETRIES` | `daemon.max_retries` | `int` |
| `HIVE_STARTING_BALANCE` | `economy.starting_balance` | `float` |
| `HIVE_PROFILES_DIR` | `profiles_dir` | `str` |
| `HIVE_LOGS_DIR` | `logs_dir` | `str` |

---

## Plugin System

Extend the SDK with custom toolkits by dropping Python files into a plugins directory. Any file that exports a `Toolkit` subclass is auto-discovered.

**Create a plugin:**

```python
# .hive/plugins/my_tools.py
from hive.runtime.tools import Toolkit, tool

class DatabaseToolkit(Toolkit):
    """Tools for querying the application database."""

    @tool()
    def query_db(self, sql: str) -> str:
        """Run a read-only SQL query.

        Args:
            sql: The SQL SELECT query to execute.
        """
        # Your database logic here
        return f"Results for: {sql}"
```

**Load plugins programmatically:**

```python
from pathlib import Path
from hive.runtime import PluginLoader

loader = PluginLoader(plugin_dirs=[Path("./.hive/plugins")])
toolkit_classes = loader.discover()

print(f"Loaded {loader.loaded_count} plugin toolkits")
for cls in toolkit_classes:
    print(f"  - {cls.__name__}")
    toolkit = cls()  # Instantiate (may need args depending on __init__)
```

**Plugin rules:**
- Files must be in a directory scanned by `PluginLoader`.
- Files starting with `_` are ignored.
- The class must be a subclass of `Toolkit` (not `Toolkit` itself).
- Each class is loaded once; re-scanning the same directory skips already-seen files.

---

## CLI Usage

The `hive` CLI is installed as an entry point when you install the package.

**Interactive chat:**

```bash
# Default model
hive agent chat

# Specify a model
hive agent chat --model claude-sonnet-4-6
hive agent chat --model gpt-5.4-nano
hive agent chat --model ollama:llama3.1
```

**Run from YAML config:**

```bash
hive agent run config.yaml
```

**Daemon system (persistent multi-agent environment):**

```bash
# Initialize a new hive
hive init

# Start the daemon (agents pick their own goals)
hive start
```

Agent profiles live in `profiles/*.yaml` and define the agent's name, role, model, tools, autonomy level, and system prompt. The daemon loads these on startup and drives agent execution in a heartbeat loop.

---

## API Reference Summary

### Imports

```python
# Core
from hive import Agent, Task, TaskResult, TaskStatus, StructuredTaskResult

# Provider factory
from hive import create_runtime_provider

# Direct providers
from hive.runtime.providers import AnthropicRuntimeProvider, OpenAIRuntimeProvider

# Tool system
from hive import tool, make_tool, collect_tools, Tool, Toolkit

# Built-in toolkits
from hive.runtime import FileToolkit, ShellToolkit, GitToolkit, DelegationToolkit

# MCP
from hive import MCPToolkit

# Memory
from hive.runtime import PersistentMemory

# Workflows
from hive.runtime import Step, Workflow

# Configuration
from hive import HiveConfig, load_config
from hive.config import get_env

# Types
from hive import Message, Role, ToolCall, ToolResult, GenerateResult
```

### Agent Methods

```python
class Agent:
    async def run(self, task: Task) -> TaskResult
    async def run_structured(self, task: Task, output_type: type[T]) -> StructuredTaskResult[T]
    async def run_once(self, message: str, context: str | None = None) -> str
    async def run_once_structured(self, message: str, output_type: type[T], context: str | None = None) -> T
    def run_once_sync(self, message: str, context: str | None = None) -> str
    def run_once_structured_sync(self, message: str, output_type: type[T], context: str | None = None) -> T
    def get_tools(self) -> list[Tool]
```

### Tool Decorator

```python
@tool(name: str | None = None, description: str | None = None)
def my_tool(param: str, count: int = 5) -> str:
    """Tool description from first paragraph of docstring.

    Args:
        param: Description of param.
        count: Description of count.
    """
    return "result"
```

### RuntimeProvider Protocol

```python
class RuntimeProvider(Protocol):
    @property
    def available(self) -> bool: ...
    async def generate(self, messages, tools?, temperature?, max_tokens?) -> Message: ...
    async def generate_with_metadata(self, messages, tools?, temperature?, max_tokens?) -> GenerateResult: ...
```
