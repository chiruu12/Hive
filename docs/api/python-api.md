# Python API

The `Hive` facade class provides a high-level Python API for programmatic control.

## Hive Facade

```python
from hive import Hive
from pathlib import Path

hive = Hive(path=Path("."))  # defaults to current directory
```

### Methods

| Method | Parameters | Returns | Description |
|--------|-----------|---------|-------------|
| `init()` | | `None` | Initialize `.hive/` directory |
| `spawn(preset, model=None)` | preset name, optional model override | `str` (agent_id) | Spawn an agent |
| `start(cycles, heartbeat, profiles, fresh)` | cycles (None=forever), heartbeat seconds, profile list, fresh start | `None` | Start daemon (blocks) |
| `stop()` | | `None` | Signal daemon to stop |
| `status()` | | `list[dict]` | Agent statuses with id, name, role, model, status, goal |
| `nudge(agent, message)` | agent name/ID, message text | `None` | Send direction to agent |
| `kill(agent)` | agent name/ID | `None` | Terminate agent |
| `inspect(run_id)` | run ID string | `dict | None` | Get run summary |

### Example

```python
from hive import Hive

hive = Hive()
hive.init()

hive.spawn("coder")
hive.spawn("gambler")
hive.spawn("philosopher")

# Run 50 cycles with 5-second heartbeat
hive.start(cycles=50, heartbeat=5)
```

## Agent

The core class for building agents.

```python
from hive import Agent, Task, Persona
from hive.models.anthropic import Anthropic
from hive.runtime import FileToolkit, ShellToolkit

agent = Agent(
    name="coder",
    model=Anthropic.lite(),
    persona=Persona(name="Coder", personality=["methodical"]),
    toolkits=[FileToolkit(), ShellToolkit()],
)
```

### Key Methods

| Method | Returns | Description |
|--------|---------|-------------|
| `await agent.run(task)` | `TaskResult` | Full ReAct loop with tools |
| `await agent.run_once(prompt)` | `str` | Single request-response |
| `await agent.run_once_structured(prompt, output_type)` | `T` | Single response as Pydantic model |
| `agent.run_once_sync(prompt)` | `str` | Synchronous one-shot |
| `agent.run_once_structured_sync(prompt, output_type)` | `T` | Synchronous structured output |

### Streaming text

Pass an `on_text` callback to stream assistant text as it is generated. When the
provider supports `Capability.STREAMING` the callback receives token deltas; with a
non-streaming provider it receives the full text in one call (via the base fallback).
The ReAct loop is otherwise unchanged -- tool calls and control flow run as usual.

```python
agent = Agent(name="coder", model=Anthropic.standard(), on_text=lambda t: print(t, end=""))
await agent.run(Task(instruction="Explain the plan, then list the files."))
```

### TaskResult

```python
result = await agent.run(Task(instruction="Write a prime checker"))
print(result.output)       # Final response text
print(result.status)       # TaskStatus.COMPLETED | .FAILED | .MAX_STEPS
print(result.steps)        # List of steps taken
print(result.input_tokens) # Total input tokens
print(result.output_tokens)# Total output tokens
```

## Workflow

Chain agents in a pipeline.

```python
from hive.runtime import Workflow, Step

workflow = Workflow(
    name="research-pipeline",
    steps=[
        Step(name="research", agent=researcher, instruction="Research {topic}", output_key="research"),
        Step(name="draft", agent=writer, instruction="Write about: {research}", output_key="draft"),
        Step(name="review", agent=reviewer, instruction="Review: {draft}", output_key="review"),
    ],
)

result = await workflow.run({"topic": "quantum computing"})
print(result["review"])
```

Steps pass context between them -- `{key}` placeholders are replaced with outputs from previous steps.

## Model Providers

All providers follow the same tier pattern:

```python
from hive.models.anthropic import Anthropic
from hive.models.openai import OpenAI
from hive.models.groq import Groq
from hive.models.fireworks import Fireworks
from hive.models.ollama import Ollama
from hive.models.lmstudio import LMStudio

# Tier presets
model = Anthropic.lite()      # Haiku
model = Anthropic.standard()  # Sonnet
model = Anthropic.pro()       # Opus

# Direct construction
model = Anthropic(model="claude-sonnet-4-6")
```

### BaseProvider Interface

All providers implement:

| Method | Returns | Description |
|--------|---------|-------------|
| `await generate_with_metadata(messages, tools, temperature, max_tokens)` | `GenerateResult` | Generate with full metadata |
| `generate_stream(messages, tools, temperature, max_tokens)` | `AsyncIterator[StreamEvent]` | Stream `TEXT` deltas then a terminal `DONE` event |
| `await generate_structured(messages, output_type, temperature, max_tokens)` | `T` | Generate as Pydantic model |
| `available` (property) | `bool` | Whether the provider can be used |
| `supports(capability)` | `bool` | Whether an optional `Capability` is supported |
| `availability()` | `Availability` | Why the provider is or isn't usable |

### Capabilities and Availability

Branch on what a provider can do with `supports()` rather than special-casing
provider classes, and use `availability()` to tell *why* a provider is unusable --
a missing API key reads differently from an unreachable local server.

```python
from hive.models.anthropic import Anthropic
from hive.models.base import Availability, Capability

model = Anthropic.standard()

model.supports(Capability.TOOLS)              # True
model.supports(Capability.STRUCTURED_OUTPUT)  # True
model.supports(Capability.STREAMING)          # True for Anthropic + OpenAI-compatible

status = model.availability()
if status is not Availability.AVAILABLE:
    print(f"unusable: {status.value}")  # e.g. "no_api_key" or "unreachable"
```

`Capability` members: `TOOLS`, `STRUCTURED_OUTPUT`, `STREAMING`.
`Availability` members: `AVAILABLE`, `NO_API_KEY`, `UNREACHABLE`, `UNKNOWN`.

### Factory

```python
from hive import create_runtime_provider

model = create_runtime_provider("anthropic:lite")
model = create_runtime_provider("openai:standard")
model = create_runtime_provider("ollama:standard")
```
