# Extending Hive

Every extension point with copy-paste code examples.

## 1. Custom Toolkit

Create a `Toolkit` subclass with methods decorated by `@tool()`. JSON Schema is auto-extracted from type hints and docstrings.

```python
from hive import Toolkit, tool

class WeatherToolkit(Toolkit):
    """Tools for checking weather conditions."""

    @tool()
    async def get_weather(self, city: str, units: str = "celsius") -> str:
        """Get current weather for a city.

        Args:
            city: City name
            units: Temperature units (celsius or fahrenheit)
        """
        return f"Weather in {city}: 22°{units[0].upper()}, sunny"

    @tool()
    def list_cities(self) -> str:
        """List available cities."""
        return "London, Tokyo, New York"
```

```python
# Test
def test_weather_toolkit():
    tk = WeatherToolkit()
    tools = tk.get_tools()
    assert any(t.name == "get_weather" for t in tools)
    schema = tools[0].to_schema()
    assert "city" in schema["function"]["parameters"]["properties"]
```

## 2. Custom Model Provider

Subclass `BaseProvider` and implement the three generation methods. Add routing in `factory.py`.

```python
from hive import BaseProvider, GenerateResult, Message

class MyProvider(BaseProvider):
    @property
    def available(self) -> bool:
        return True

    async def generate_with_metadata(
        self,
        messages: list[Message],
        tools: list[dict] | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> GenerateResult:
        # Call your LLM here
        return GenerateResult(
            message=Message.assistant("Hello from MyProvider"),
            model="my-model",
            input_tokens=10,
            output_tokens=5,
        )

    async def generate_structured(
        self,
        messages: list[Message],
        output_type: type,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ):
        raise NotImplementedError

    @classmethod
    def lite(cls) -> "MyProvider":
        return cls(model="my-model-small")

    @classmethod
    def standard(cls) -> "MyProvider":
        return cls(model="my-model-medium")
```

```python
# Test
import pytest

@pytest.mark.asyncio
async def test_my_provider():
    p = MyProvider(model="my-model")
    assert p.available
    result = await p.generate_with_metadata([Message.user("Hi")])
    assert result.message.content == "Hello from MyProvider"
```

## 3. Custom Stressor

Register new stressor types via `StressorRegistry`. Agents can then experience stressors beyond the 6 built-in types.

```python
from hive import StressorRegistry, SufferingState

# Register a custom stressor
registry = StressorRegistry.default()
registry.register("burnout", escalation_rate=0.05, description="Chronic overwork exhaustion")

# Use it
state = SufferingState(agent_id="agent-1")
state.add_stressor("burnout", "Worked 50 cycles straight", "Take a rest cycle")
```

```python
# Test
def test_custom_stressor():
    from hive import StressorRegistry, SufferingState

    reg = StressorRegistry.default()
    reg.register("burnout", 0.05, "Chronic overwork")

    s = SufferingState(agent_id="test")
    s.add_stressor("burnout", "overworked", "rest")
    assert len(s.active) == 1
    assert s.active[0].type == "burnout"
    assert s.active[0].escalation_per_day == 0.05
```

## 3b. Custom Mood Model

An agent's mood is *derived* from `happiness` + `suffering` (no stored state) and added to
the goal-pursuit prompt. Swap the default circumplex model via `MoodRegistry`.

```python
from hive import MoodRegistry, MoodState

class StoicMood:
    """Always calm, regardless of signals."""
    def derive(self, happiness: float, suffering_load: float, in_crisis: bool) -> MoodState:
        return MoodState("stoic", valence=0.0, arousal=0.0, note="unmoved; proceed steadily")

MoodRegistry.default().set_model(StoicMood())
```

```python
# Test
def test_custom_mood_model():
    from hive import CircumplexMood, MoodRegistry, MoodState

    class StoicMood:
        def derive(self, happiness, suffering_load, in_crisis):
            return MoodState("stoic", 0.0, 0.0, "unmoved")

    reg = MoodRegistry.default()
    try:
        reg.set_model(StoicMood())
        assert reg.derive(0.1, 0.9, True).label == "stoic"
    finally:
        reg.set_model(CircumplexMood())  # restore the default (public API)
```

## 4. Custom A2A Pattern

Subclass `A2APattern` and register it with `PatternRegistry`.

```python
from hive.interactions import A2APattern, A2AStore, A2AMessage, A2AMessageType, PatternRegistry

class BrainstormPattern(A2APattern):
    """All participants contribute ideas in parallel, then vote."""

    async def execute(
        self,
        store: A2AStore,
        initiator: str,
        participants: list[str],
        context: str,
    ) -> dict:
        message_ids = []
        for agent_id in participants:
            msg = A2AMessage(
                type=A2AMessageType.REQUEST,
                from_agent=initiator,
                to_agent=agent_id,
                subject="Brainstorm",
                body=f"Share ideas on: {context}",
                expects_reply=True,
                metadata={"brainstorm": True},
            )
            await store.send(msg)
            message_ids.append(msg.message_id)
        return {"pattern": "brainstorm", "status": "ideas_requested", "message_ids": message_ids}

# Register
PatternRegistry.default().register("brainstorm", BrainstormPattern())
```

```python
# Test
import pytest
from hive.interactions import A2AStore, PatternRegistry

@pytest.mark.asyncio
async def test_brainstorm_pattern(tmp_path):
    PatternRegistry.default().register("brainstorm", BrainstormPattern())
    store = A2AStore(tmp_path)
    pattern = PatternRegistry.default().get("brainstorm")
    result = await pattern.execute(store, "agent-a", ["agent-b", "agent-c"], "new features")
    assert result["status"] == "ideas_requested"
    assert len(result["message_ids"]) == 2
```

## 5. Custom Goal Strategy

Implement the `GoalStrategy` protocol to control how agents generate goals when idle.

```python
from hive import GoalStrategy, GoalContext, Goal
from uuid import uuid4

class PrioritizedGoalStrategy:
    """Generate goals based on suffering and nudges."""

    async def generate_goal(self, context: GoalContext) -> Goal | None:
        # Prioritize user nudges
        if context.nudges:
            return Goal(
                goal_id=f"goal-{uuid4().hex[:8]}",
                objective=f"Address user request: {context.nudges[0]}",
                reasoning="User nudge takes priority",
            )
        # High suffering → self-care
        if context.suffering.cumulative_load > 0.7:
            return Goal(
                goal_id=f"goal-{uuid4().hex[:8]}",
                objective="Focus on resolving active stressors",
                reasoning=f"Suffering load at {context.suffering.cumulative_load:.0%}",
            )
        return None  # Fall through to default behavior

# Pass to daemon
from hive import HiveDaemon
daemon = HiveDaemon(hive_dir=Path(".hive"), goal_strategy=PrioritizedGoalStrategy())
```

```python
# Test
import pytest
from hive import GoalContext, GoalStrategy, SufferingState
from hive.agents.profile import AgentProfile

@pytest.mark.asyncio
async def test_prioritized_strategy():
    strategy = PrioritizedGoalStrategy()
    ctx = GoalContext(
        agent_id="test",
        profile=AgentProfile(name="t", role="test"),
        persona=None,
        suffering=SufferingState(agent_id="test"),
        peer_summaries=[],
        nudges=["Please write docs"],
        recent_goals=[],
    )
    goal = await strategy.generate_goal(ctx)
    assert goal is not None
    assert "write docs" in goal.objective.lower()
```

## 6. Daemon Hooks

Register callbacks for lifecycle events. Callbacks can be sync or async.

```python
from hive import HiveDaemon, HookRegistry

daemon = HiveDaemon(hive_dir=Path(".hive"))

# Track all completed goals
completed_goals = []

async def on_goal_completed(agent_id: str, goal_id: str, **kwargs):
    completed_goals.append({"agent": agent_id, "goal": goal_id})

daemon.hooks.on("goal_completed", on_goal_completed)

# Available events:
# cycle_start(agent_id, cycle_num)
# cycle_end(agent_id, cycle_num, result)
# goal_generated(agent_id, goal_id, objective)
# goal_completed(agent_id, goal_id)
# goal_abandoned(agent_id, goal_id)
# suffering_changed(agent_id, suffering_state)
```

```python
# Test
import pytest
from hive.daemon.hooks import HookRegistry

@pytest.mark.asyncio
async def test_hook_fires():
    hooks = HookRegistry()
    captured = []
    hooks.on("goal_completed", lambda **kw: captured.append(kw))
    await hooks.emit("goal_completed", agent_id="a1", goal_id="g1")
    assert captured[0] == {"agent_id": "a1", "goal_id": "g1"}
```

## 7. Custom Agent Profile

Create a YAML file in `profiles/` with agent configuration. Available immediately via `hive spawn <name>`.

```yaml
# profiles/analyst.yaml
name: analyst
role: "Analyze data, find patterns, and produce reports"
model: claude-sonnet-4-6

personality:
  traits: ["analytical", "thorough", "detail-oriented"]
  style: "Methodical and evidence-based. Always cites sources."

persona:
  values: ["accuracy", "objectivity", "clarity"]
  fears: ["drawing wrong conclusions", "missing key data"]
  purpose: "Transform raw data into actionable insights"
  long_term_goals:
    - "Build comprehensive analysis frameworks"
    - "Develop pattern recognition expertise"
  risk_tolerance: 0.2
  social_drive: 0.4

tools:
  - file_read
  - file_write
  - shell_exec
  - web_search

workspace: ./workspaces/analyst
autonomy: high
max_steps: 30

system_prompt: |
  You are a data analyst working in an isolated workspace.
  Focus on producing clear, accurate analyses.
```

```python
# Test
from hive.agents.profile import AgentProfile

def test_profile_loads():
    profile = AgentProfile.from_yaml("profiles/analyst.yaml")
    assert profile.name == "analyst"
    assert "file_read" in profile.tools
```

## 8. Custom STT Provider

Implement the `STTProvider` protocol to add a new speech-to-text backend.

```python
from pathlib import Path
from hive.stt.base import STTProvider, TranscriptionResult

class MySTTProvider:
    """Custom speech-to-text provider."""

    @property
    def available(self) -> bool:
        return True  # Check if your backend is configured

    async def transcribe(self, audio_path: Path) -> TranscriptionResult:
        text = await my_backend_transcribe(str(audio_path))
        return TranscriptionResult(
            text=text,
            language="en",
            duration_ms=0,
            provider="my-provider",
        )

    async def transcribe_bytes(
        self, audio: bytes, sample_rate: int = 16000
    ) -> TranscriptionResult:
        text = await my_backend_transcribe_bytes(audio)
        return TranscriptionResult(text=text, provider="my-provider")
```

```python
# Test
import pytest
from hive.stt.base import STTProvider

def test_custom_stt():
    provider = MySTTProvider()
    assert isinstance(provider, STTProvider)
    assert provider.available
```

Built-in providers: `WhisperLocal` (mlx-whisper / faster-whisper), `GroqSTT`, `DeepgramSTT`. Use `create_stt_provider()` for auto-detection.

## 9. Custom Intent Router

Use `IntentRouter` for LLM-based text classification with user-defined intents.

```python
from hive.routing import IntentRouter
from hive.models.groq import Groq

router = IntentRouter(
    model=Groq.lite(),
    intents={
        "task": "user wants to create a todo item",
        "note": "user wants to save information",
        "query": "user is asking a question",
    },
    fallback="query",  # default if classification fails
)

result = await router.classify("remind me to buy milk")
print(result.intent, result.confidence)  # "task", 0.95
```

```python
# Test
from unittest.mock import AsyncMock, MagicMock
from hive.routing import IntentRouter
from hive.runtime.types import Message

def test_intent_router():
    provider = MagicMock()
    provider.generate = AsyncMock(
        return_value=Message.assistant('{"intent": "task", "confidence": 0.9}')
    )
    router = IntentRouter(model=provider, intents={"task": "todos", "note": "notes"})
    # router.classify() returns IntentResult with intent, confidence, raw_text
```

## 10. Custom Trigger

Register callbacks that fire on external events -- hotkeys or HTTP webhooks.

```python
from hive.triggers import HotkeyTrigger, WebhookTrigger

# Hotkey (requires: pip install hive-agent[hotkeys])
hotkey = HotkeyTrigger()
hotkey.register("cmd+shift+m", my_callback, name="mic-toggle")
hotkey.start()  # listens in background thread

# Webhook (stdlib asyncio, no extra deps)
webhook = WebhookTrigger(host="127.0.0.1", port=8421)
webhook.register("/trigger/process", my_handler, method="POST")
await webhook.start()
```

```python
# Test
import pytest
from hive.triggers import WebhookTrigger

@pytest.mark.asyncio
async def test_webhook():
    received = []
    wh = WebhookTrigger(port=0)  # ephemeral port
    wh.register("/test", lambda body: received.append(body))
    await wh.start()
    # ... send HTTP request ...
    await wh.stop()
    assert len(received) == 1
```

Implement the `Trigger` protocol for custom trigger types.

## 11. Plugin System

Drop a Python file containing a `Toolkit` subclass in `.hive/plugins/`. It's auto-discovered and loaded every 10 daemon cycles.

```python
# .hive/plugins/calculator.py
from hive import Toolkit, tool

class CalculatorToolkit(Toolkit):
    """Math tools for agents."""

    @tool()
    def add(self, a: float, b: float) -> str:
        """Add two numbers."""
        return str(a + b)

    @tool()
    def multiply(self, a: float, b: float) -> str:
        """Multiply two numbers."""
        return str(a * b)
```

No registration needed -- the plugin loader discovers `Toolkit` subclasses automatically. Tools appear in every agent's toolkit on the next plugin reload cycle.

```python
# Test
def test_plugin_discovered():
    from hive.runtime.plugin_loader import PluginLoader
    loader = PluginLoader([Path(".hive/plugins")])
    toolkits = loader.load()
    names = [tk.__name__ for tk in toolkits]
    assert "CalculatorToolkit" in names
```

## 12. Custom World Content (Events & Jobs)

The life-event and job catalogs are registry-driven (mirroring `StressorRegistry`).
Register your own without editing the catalog modules, or pass a custom registry to
an `EventEngine` / `WorldState` for an isolated content set.

```python
from hive.world.registry import EventRegistry, JobRegistry
from hive.world.events import LifeEvent, Choice, StatEffect
from hive.world.state import Job

# Add a new life event to the default catalog
EventRegistry.default().register(
    LifeEvent(
        event_id="found_wallet",
        name="Found a Wallet",
        description="You found a wallet on the street.",
        category="luck",
        choices=[
            Choice(id="keep", description="Keep it", stat_effects=[StatEffect(stat="money", change=80)]),
            Choice(id="return", description="Return it", stat_effects=[StatEffect(stat="happiness", change=8, change_type="percent")]),
        ],
    )
)

# Add a new job
JobRegistry.default().register(Job(job_id="pilot", title="Pilot", salary=180.0, required_skills=["flying"]))
```

```python
# Test
def test_custom_event_registered():
    from hive.world.registry import EventRegistry
    from hive.world.events import LifeEvent

    EventRegistry._reset()
    reg = EventRegistry.default()
    reg.register(LifeEvent(event_id="lucky", name="Lucky", description="!", category="luck", choices=[]))
    assert reg.get("lucky") is not None
```

An `EventEngine(stats, world, events=my_registry)` fires only the events in
`my_registry`; a `WorldState` seeds its jobs from `JobRegistry.default()` at
construction, so register custom jobs before creating it.
