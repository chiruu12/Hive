# hive-agent SDK Reference (for AI Coding Assistants)

## Package

| Field | Value |
|-------|-------|
| Package | `hive-agent` |
| Install | `pip install hive-agent` / `uv add hive-agent` |
| Python | `>=3.11` |
| Import | `from hive import ...` |

## Exports

### Top-level (`from hive import ...`)

```
Agent, AgentProfile, AgentState, AgentStatus, collect_tools, CommsToolkit,
ConversationMemory, create_runtime_provider, DaemonAgentAdapter, EventLog,
EventType, ExecutionContext, ExistenceLoop, GenerateResult, GoalOutcome,
Hive, HiveConfig, HiveDaemon, HiveEvent, HiveStore, initialize_hive,
load_config, make_tool, MCPToolkit, MemoryToolkit, Message, PersistentMemory,
Role, Step, StressorType, StructuredGenerateResult, StructuredTaskResult,
SufferingState, Task, TaskResult, TaskStatus, Tool, ToolCall, ToolResult,
Toolkit, tool, Workflow, WorldState, WorldToolkit
```

### Runtime (`from hive.runtime import ...`)

```
Agent, collect_tools, CommsToolkit,
ConversationMemory, DaemonAgentAdapter, DaemonDelegationToolkit,
DelegationToolkit, FileToolkit, GenerateResult, GitToolkit, GoalOutcome,
make_tool, MemoryToolkit, Message, PersistentMemory,
PluginLoader, Role, BaseProvider, ShellToolkit, Step,
StructuredGenerateResult, StructuredTaskResult, Task, TaskResult, TaskStatus,
Tool, ToolCall, ToolResult, Toolkit, tool, Workflow, WorldToolkit
```

### Models (`from hive.models.* import ...`)

```
BaseProvider              # from hive.models.base
Anthropic                 # from hive.models.anthropic
OpenAI                    # from hive.models.openai
Groq                      # from hive.models.groq
Fireworks                 # from hive.models.fireworks
Ollama                    # from hive.models.ollama
LMStudio                  # from hive.models.lmstudio
create_runtime_provider   # from hive.models.factory (also from hive)
```

---

## Agent

### Constructor

```python
from hive import Agent
from hive.models.anthropic import Anthropic  # or any provider

agent = Agent(
    name: str,                          # required
    model: BaseProvider,                # required
    system_prompt: str = "",
    toolkits: list[Toolkit] | None = None,
    tools: list[Tool] | None = None,
    memory: PersistentMemory | None = None,
    max_steps: int = 25,
    temperature: float = 0.0,
    max_cost_usd: float = 0.0,         # 0 = no limit
    max_tokens: int = 0,               # 0 = default 4096
)
```

### Methods

| Method | Signature | Returns | Description |
|--------|-----------|---------|-------------|
| `run` | `async (task: Task)` | `TaskResult` | Full ReAct loop with tools |
| `run_structured` | `async (task: Task, output_type: type[T])` | `StructuredTaskResult[T]` | One-shot structured output via task |
| `run_once` | `async (message: str, context: str \| None = None)` | `str` | Single turn, at most one tool round |
| `run_once_structured` | `async (message: str, output_type: type[T], context: str \| None = None)` | `T` | Single turn, returns parsed model |
| `run_once_sync` | `(message: str, context: str \| None = None)` | `str` | Sync wrapper for `run_once` |
| `run_once_structured_sync` | `(message: str, output_type: type[T], context: str \| None = None)` | `T` | Sync wrapper for `run_once_structured` |
| `get_tools` | `()` | `list[Tool]` | All tools from toolkits + extra tools |

### Minimal Example

```python
import asyncio
from hive import Agent, Task
from hive.models.anthropic import Anthropic

agent = Agent(
    name="helper",
    model=Anthropic.lite(),
    system_prompt="You are a helpful assistant.",
)

result = asyncio.run(agent.run(Task(instruction="What is 2+2?")))
print(result.output)
```

### Sync One-Shot Example

```python
from hive import Agent
from hive.models.anthropic import Anthropic

agent = Agent(name="q", model=Anthropic.lite())
answer = agent.run_once_sync("What is the capital of France?")
print(answer)
```

---

## Task / TaskResult

```python
from hive import Task, TaskResult, TaskStatus, StructuredTaskResult

# Task
Task(
    instruction: str,                    # required
    id: str = "task-{auto_hex}",
    context: dict[str, Any] = {},
    max_steps: int = 25,
)

# TaskResult fields
TaskResult(
    task_id: str,
    status: TaskStatus,                  # COMPLETED | FAILED | MAX_STEPS | PENDING | RUNNING
    output: str = "",
    steps_taken: int = 0,
    tool_calls_made: int = 0,
    error: str | None = None,
    duration_seconds: float = 0.0,
)

# StructuredTaskResult adds:
StructuredTaskResult[T](
    ...TaskResult fields...,
    parsed: T | None,                    # validated model on COMPLETED; None on FAILED
)
```

---

## Message

```python
from hive import Message, Role

# Static constructors (preferred)
Message.system("You are a coder.")
Message.user("Write hello world.")
Message.assistant("Here it is.", tool_calls=[...])
Message.tool_result(tool_call_id="id", content="output", is_error=False, name="tool_name")

# Role enum: SYSTEM | USER | ASSISTANT | TOOL

# Fields (frozen dataclass)
# .role: Role
# .content: str
# .tool_calls: tuple[ToolCall, ...]
# .tool_call_id: str
# .name: str
# .is_error: bool
```

---

## Tool System

### Pattern 1: `@tool` on Toolkit Methods

```python
from hive import Agent, Toolkit, tool
from hive.models.anthropic import Anthropic

class SearchToolkit(Toolkit):
    @tool()
    def search(self, query: str, max_results: int = 5) -> str:
        """Search a knowledge base.

        Args:
            query: The search query string.
            max_results: Maximum number of results to return.
        """
        return f"Found {max_results} results for: {query}"

agent = Agent(
    name="researcher",
    model=Anthropic.lite(),
    toolkits=[SearchToolkit()],
)
```

### Pattern 2: Standalone Functions with `make_tool`

```python
from hive import tool, make_tool

@tool()
def calculate(expression: str) -> str:
    """Evaluate a math expression.

    Args:
        expression: A Python math expression to evaluate.
    """
    return str(eval(expression))

t = make_tool(calculate)  # -> Tool
```

### Pattern 3: Batch with `collect_tools`

```python
from hive import tool, collect_tools

@tool()
def add(a: int, b: int) -> str:
    """Add two numbers.

    Args:
        a: First number.
        b: Second number.
    """
    return str(a + b)

@tool()
def multiply(a: int, b: int) -> str:
    """Multiply two numbers.

    Args:
        a: First number.
        b: Second number.
    """
    return str(a * b)

tools = collect_tools(add, multiply)  # -> list[Tool]
```

### Pattern 4: Async Tool

```python
from hive import Toolkit, tool

class APIToolkit(Toolkit):
    @tool()
    async def fetch_data(self, url: str) -> str:
        """Fetch data from a URL.

        Args:
            url: The URL to fetch.
        """
        import httpx
        async with httpx.AsyncClient() as client:
            resp = await client.get(url)
            return resp.text[:5000]
```

### Tool Decorator Options

```python
@tool()                              # name = function name, description = docstring
@tool(name="custom_name")           # override tool name
@tool(description="Custom desc")    # override description
@tool(name="foo", description="d")  # override both
```

### Supported Parameter Types

| Python Type | JSON Schema Type |
|-------------|-----------------|
| `str` | `"string"` |
| `int` | `"integer"` |
| `float` | `"number"` |
| `bool` | `"boolean"` |
| `dict` | `"object"` |
| `list[str]` | `"array"` with `"items": {"type": "string"}` |
| `dict[str, int]` | `"object"` with `"additionalProperties"` |
| `Literal["a", "b"]` | `"string"` with `"enum": ["a", "b"]` |
| `str \| None` | `"string"` (optional) |
| `BaseModel` subclass | inlined object schema |
| `@dataclass` | inlined object schema |
| unannotated | `"string"` (with warning) |

---

## Built-in Toolkits

### FileToolkit

```python
from pathlib import Path
from hive.tools.file import FileToolkit

ft = FileToolkit(workspace=Path("/tmp/work"))
```

| Tool | Parameters | Description |
|------|-----------|-------------|
| `file_read` | `path: str, offset: int = 0, limit: int = 500` | Read file lines |
| `file_write` | `path: str, content: str` | Write file (creates dirs) |
| `file_edit` | `path: str, old_text: str, new_text: str` | Replace exact string (must be unique) |
| `list_dir` | `path: str = ".", max_depth: int = 2` | List directory tree |

### ShellToolkit

```python
from pathlib import Path
from hive.tools.shell import ShellToolkit

st = ShellToolkit(workspace=Path("/tmp/work"), timeout=30, restrict=True)
# restrict=True: command allowlist (python, git, npm, curl, etc.)
# restrict=False: full shell access
```

| Tool | Parameters | Description |
|------|-----------|-------------|
| `shell_exec` | `command: str` | Execute shell command (async) |

### GitToolkit

```python
from pathlib import Path
from hive.tools.git import GitToolkit

gt = GitToolkit(workspace=Path("/tmp/work"))
```

| Tool | Parameters | Description |
|------|-----------|-------------|
| `git_status` | (none) | `git status --short` |
| `git_diff` | `staged: bool = False` | Show diff |
| `git_log` | `count: int = 10` | Show recent commits |
| `git_add` | `path: str = "."` | Stage files |
| `git_commit` | `message: str` | Create commit |
| `git_init` | (none) | Init repo |

### DelegationToolkit

```python
from hive.tools.delegation import DelegationToolkit

delegation = DelegationToolkit(agents={"researcher": agent_a, "coder": agent_b})
leader = Agent(name="lead", model=provider, toolkits=[delegation])
```

| Tool | Parameters | Description |
|------|-----------|-------------|
| `delegate_task` | `agent_name: str, task: str` | Run task on named agent (async) |
| `list_agents` | (none) | List available agent names |

---

## Providers

### Tier Presets (Recommended)

Each provider class has `.lite()`, `.standard()`, `.pro()` classmethods:

```python
from hive.models.anthropic import Anthropic
from hive.models.openai import OpenAI
from hive.models.groq import Groq
from hive.models.fireworks import Fireworks
from hive.models.ollama import Ollama
from hive.models.lmstudio import LMStudio

provider = Anthropic.lite()        # Claude Haiku (fast, cheap)
provider = Anthropic.standard()    # Claude Sonnet (balanced)
provider = Anthropic.pro()         # Claude Opus (most capable)
provider = OpenAI.lite()           # GPT-5.4 Nano
provider = Groq.lite()             # Llama on Groq
provider = Ollama.lite()           # Local model
```

### Factory (String-Based Routing)

```python
from hive import create_runtime_provider

provider = create_runtime_provider("claude-haiku-4-5")
```

`create_runtime_provider` is located in `hive.models.factory` and re-exported from `hive`.

### Routing Table

| Model String | Provider | Env Var Required |
|-------------|----------|-----------------|
| `claude-haiku-4-5` | `Anthropic` | `ANTHROPIC_API_KEY` |
| `claude-sonnet-4-6` | `Anthropic` | `ANTHROPIC_API_KEY` |
| `gpt-5.4-nano` | `OpenAI` | `OPENAI_API_KEY` |
| `gpt-5.4-mini` | `OpenAI` | `OPENAI_API_KEY` |
| `fireworks:deepseek-v4-pro` | `Fireworks` | `FIREWORKS_API_KEY` |
| `groq:llama-3.3-70b-versatile` | `Groq` | `GROQ_API_KEY` |
| `ollama:llama3.2` | `Ollama` (localhost:11434) | none |
| `lmstudio:loaded-model` | `LMStudio` (localhost:1234) | none |

### Direct Construction

```python
from hive.models.anthropic import Anthropic
from hive.models.openai import OpenAI
from hive.models.ollama import Ollama

# Anthropic
p = Anthropic(model="claude-haiku-4-5", api_key="sk-ant-...")

# OpenAI
p = OpenAI(model="gpt-5.4-nano", api_key="sk-...")

# Custom base URL (Fireworks, Together, etc.)
p = OpenAI(
    model="accounts/fireworks/models/deepseek-v3",
    api_key="fw-...",
    base_url="https://api.fireworks.ai/inference/v1",
)

# Local (Ollama)
p = Ollama(model="llama3.2")
```

---

## Structured Output

### One-Shot (Returns Model Directly)

```python
from pydantic import BaseModel
from hive import Agent
from hive.models.anthropic import Anthropic

class Sentiment(BaseModel):
    label: str
    confidence: float

agent = Agent(name="s", model=Anthropic.lite())
result = agent.run_once_structured_sync("Analyze: 'I love this!'", output_type=Sentiment)
# result is a Sentiment instance
print(result.label, result.confidence)
```

### Task-Based (Returns StructuredTaskResult)

```python
import asyncio
from pydantic import BaseModel
from hive import Agent, Task
from hive.models.anthropic import Anthropic

class Plan(BaseModel):
    steps: list[str]
    estimated_hours: float

agent = Agent(name="planner", model=Anthropic.lite())

result = asyncio.run(
    agent.run_structured(
        Task(instruction="Plan a blog migration"),
        output_type=Plan,
    )
)
print(result.status)           # TaskStatus.COMPLETED
print(result.parsed.steps)     # ["Step 1...", ...]
print(result.parsed.estimated_hours)
```

---

## MCP Integration

```python
import asyncio
from hive import Agent, Task, MCPToolkit
from hive.models.anthropic import Anthropic

async def main():
    async with await MCPToolkit.from_stdio(
        "npx", ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
    ) as mcp:
        agent = Agent(
            name="fs-agent",
            model=Anthropic.lite(),
            toolkits=[mcp],
        )
        result = await agent.run(Task(instruction="List all .txt files in /tmp"))
        print(result.output)

asyncio.run(main())
```

### MCPToolkit.from_stdio

```python
MCPToolkit.from_stdio(
    command: str,                        # executable (e.g. "npx", "python")
    args: list[str] | None = None,       # command arguments
    env: dict[str, str] | None = None,   # environment variables
    cwd: str | Path | None = None,       # working directory
) -> MCPToolkit
```

### MCPToolkit.from_config

```python
MCPToolkit.from_config({
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
    "env": {"NODE_ENV": "production"},
    "cwd": "/opt/servers",
})
```

---

## Workflow

```python
import asyncio
from hive import Agent
from hive.models.anthropic import Anthropic
from hive.runtime import Workflow, Step

lite = Anthropic.lite()
researcher = Agent(name="researcher", model=lite)
writer = Agent(name="writer", model=lite)

workflow = Workflow(
    name="blog-pipeline",
    steps=[
        Step(
            name="research",
            agent=researcher,
            instruction="Research the topic: {topic}",
            output_key="research",
        ),
        Step(
            name="write",
            agent=writer,
            instruction="Write a blog post using this research:\n{research}",
            output_key="draft",
        ),
    ],
)

ctx = asyncio.run(workflow.run({"topic": "async Python"}))
print(ctx["draft"])
```

### Step with Custom Function

```python
from hive.runtime import Step

async def transform(context: dict) -> str:
    return context["raw_data"].upper()

step = Step(name="transform", fn=transform, output_key="transformed")
```

---

## PersistentMemory

```python
from pathlib import Path
from hive import Agent, PersistentMemory
from hive.models.anthropic import Anthropic

memory = PersistentMemory(agent_name="coder", hive_dir=Path(".hive"))

agent = Agent(
    name="coder",
    model=Anthropic.lite(),
    memory=memory,
)
# Agent auto-recalls relevant memories at task start
# Store/recall manually:
# await memory.store("learned X about the codebase")
# entries = await memory.recall("database schema", limit=5)
```

---

## Hive Facade (Daemon Mode)

```python
from pathlib import Path
from hive import Hive

h = Hive(path=Path("."))
h.init()                                # optional -- .hive/ is created lazily on first use
agent_id = h.spawn("coder")            # spawn from preset profile
h.spawn("coder", model="gpt-5.4-nano")  # override model
h.start(cycles=10, heartbeat=10)        # run 10 daemon cycles (blocking)
h.status()                              # -> list[dict] with agent_id, name, role, status, goal
h.nudge("coder", "write tests next")   # send message to agent
h.kill("coder")                         # terminate agent
h.stop()                                # signal daemon to stop
```

`Hive` is also a context manager -- `init()` is optional, and the daemon is
stopped on exit:

```python
with Hive(Path(".")) as h:              # sync
    h.spawn("coder")

async with Hive(Path(".")) as h:        # async (native init, no thread hop)
    h.spawn("coder")
```

---

## Environment Variables

| Variable | Provider | Required For |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | Anthropic | `claude-*` models |
| `OPENAI_API_KEY` | OpenAI | `gpt-*` models |
| `FIREWORKS_API_KEY` | Fireworks | `fireworks:*` models |
| `GROQ_API_KEY` | Groq | `groq:*` models |
| (none) | Ollama | `ollama:*` (local) |
| (none) | LM Studio | `lmstudio:*` (local) |

---

## Common Recipes

### Agent with Tools (Full ReAct Loop)

```python
import asyncio
from pathlib import Path
from hive import Agent, Task
from hive.models.anthropic import Anthropic
from hive.tools.file import FileToolkit
from hive.tools.shell import ShellToolkit

agent = Agent(
    name="dev",
    model=Anthropic.standard(),
    system_prompt="You are a senior developer.",
    toolkits=[
        FileToolkit(workspace=Path("./project")),
        ShellToolkit(workspace=Path("./project"), restrict=False),
    ],
    max_steps=15,
    max_cost_usd=0.50,
)

result = asyncio.run(agent.run(Task(instruction="Add type hints to all functions in main.py")))
print(result.status, result.steps_taken, result.tool_calls_made)
```

### Multi-Agent Delegation

```python
import asyncio
from hive import Agent, Task
from hive.models.anthropic import Anthropic
from hive.tools.delegation import DelegationToolkit
from hive.tools.file import FileToolkit
from hive.tools.shell import ShellToolkit
from pathlib import Path

ws = Path("./project")

researcher = Agent(
    name="researcher",
    model=Anthropic.lite(),
    toolkits=[ShellToolkit(workspace=ws)],
)
coder = Agent(
    name="coder",
    model=Anthropic.standard(),
    toolkits=[FileToolkit(workspace=ws), ShellToolkit(workspace=ws)],
)

lead = Agent(
    name="lead",
    model=Anthropic.standard(),
    toolkits=[DelegationToolkit(agents={"researcher": researcher, "coder": coder})],
    system_prompt="You are a tech lead. Delegate research and coding tasks.",
)

result = asyncio.run(lead.run(Task(instruction="Add a /health endpoint to the API")))
```

### Mixed Toolkits + Standalone Tools

```python
from hive import Agent, Toolkit, tool, make_tool
from hive.models.anthropic import Anthropic
from hive.tools.file import FileToolkit
from pathlib import Path

@tool()
def timestamp() -> str:
    """Return the current UTC timestamp."""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()

agent = Agent(
    name="mixed",
    model=Anthropic.lite(),
    toolkits=[FileToolkit(workspace=Path("/tmp/work"))],
    tools=[make_tool(timestamp)],
)
```

---

## Gotchas

1. `@tool()` needs parentheses -- it is a decorator factory, not a decorator
2. `run()` and `run_once()` are async -- use `asyncio.run()` or the `_sync` variants
3. Tool functions MUST have type annotations -- untyped params default to `str`
4. Docstrings with an `Args:` section are how parameter descriptions reach the LLM
5. `Toolkit.get_tools()` skips methods starting with `_`
6. `ShellToolkit(restrict=True)` uses a command allowlist -- pass `restrict=False` for full access
7. `FileToolkit` blocks path traversal outside its `workspace` directory
8. `max_cost_usd=0` means unlimited -- set a budget for production use
9. `run_once` does at most one tool-use round then a final generation
10. `run` does the full multi-step ReAct loop -- use for complex multi-tool tasks
11. Local models (`ollama:*`, `lmstudio:*`) may not support native structured output -- fallback is automatic
12. `.env` files are NOT auto-loaded into `os.environ` -- set env vars explicitly or use `dotenv`
13. `run_once_sync` / `run_once_structured_sync` create a new event loop -- do not call from within an existing async context (it uses a thread pool as a workaround, but prefer async when possible)
14. `collect_tools()` applies `@tool()` automatically if the function is not already decorated
15. Tool return values are stringified -- return `str` for predictable LLM input; `dict`/`list` are JSON-serialized
