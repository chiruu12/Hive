# SDK Quickstart

Build your first agent in under 10 lines.

## Hello World

```python
import asyncio
from hive import Agent, Task
from hive.models.anthropic import Anthropic

async def main():
    agent = Agent(name="assistant", model=Anthropic.lite())
    result = await agent.run(Task(instruction="What is the capital of France?"))
    print(result.output)

asyncio.run(main())
```

## Synchronous One-Shot

For scripts where you don't need the full ReAct loop:

```python
from hive import Agent
from hive.models.anthropic import Anthropic

agent = Agent(name="assistant", model=Anthropic.lite())
result = agent.run_once_sync("Explain quantum computing in one paragraph")
print(result)
```

## Adding Tools

Decorate any function with `@tool` -- JSON Schema is auto-extracted from type hints:

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

Or use built-in toolkits:

```python
from hive import Agent
from hive.models.anthropic import Anthropic
from hive.runtime import FileToolkit, ShellToolkit

agent = Agent(
    name="coder",
    model=Anthropic.lite(),
    toolkits=[FileToolkit(), ShellToolkit()],
)
```

## Structured Output

Get typed responses using Pydantic models:

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
print(f"{review.title}: {review.rating}/10")
```

## Adding Personality

Give your agent a Persona for dynamic behavior:

```python
from hive import Agent, Persona
from hive.models.anthropic import Anthropic

agent = Agent(
    name="gambler",
    model=Anthropic.lite(),
    persona=Persona(
        name="The Gambler",
        personality=["bold", "intuitive", "reckless"],
        values=["expected value", "asymmetric upside"],
        fears=["missing out", "becoming too cautious"],
        purpose="Find opportunities others fear",
        risk_tolerance=0.85,
        social_drive=0.6,
    ),
)
```

Persona is optional -- plain `Agent(name=..., model=...)` works without it.

## Next Steps

- [Developer Guide](../guide/developer-guide.md) -- full SDK reference with all features
- [Persona System](../guide/persona.md) -- how personality evolves at runtime
- [Examples](../examples/index.md) -- 15 runnable code samples
