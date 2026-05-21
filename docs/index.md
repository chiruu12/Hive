# Hive

**Local-first agent OS. Spawn persistent AI agents that collaborate, write code, and use tools autonomously.**

`from hive import Agent` gives you an agent that **comes alive** -- not stateless function calls, but persistent entities with personality, suffering, and evolution.

<!-- Demo GIF: run demo/record.sh -->

## What Makes Hive Different

Most agent frameworks treat agents as stateless function executors. Hive agents are **persistent entities with inner life**:

- **Persona system** -- personality traits, values, fears, and dynamic behavioral state
- **Suffering system** -- 6 stressor types that mechanically change agent behavior at runtime
- **Economy simulation** -- jobs, money, skills, random life events
- **Agent journals** -- persistent notepads with visible inner monologue
- **A2A protocol** -- typed inter-agent messaging with collaboration patterns
- **Sub-agent spawning** -- parent-child lifecycle with depth limits

## Quick Start

```bash
pip install hive-agent
```

### SDK Usage

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

### Simulation Mode

```bash
hive init && hive demo survival
```

3 agents with different personalities compete in a simulated economy for 30 cycles. Watch them struggle, gamble, philosophize, and suffer.

## Multi-Model Support

6 providers with tier presets (`.lite()`, `.standard()`, `.pro()`):

| Provider | `.lite()` | `.standard()` | `.pro()` |
|----------|-----------|---------------|----------|
| Anthropic | Haiku | Sonnet | Opus |
| OpenAI | GPT-5.4 Nano | GPT-5.4 Mini | GPT-5.4 |
| Groq | Llama 8B | GPT-OSS 20B | Llama 70B |
| Fireworks | MiniMax | DeepSeek | Kimi |
| Ollama | Local model | Local model | - |
| LM Studio | Auto | - | - |

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

## Next Steps

- [Installation](getting-started/installation.md) -- set up Hive
- [SDK Quickstart](getting-started/quickstart.md) -- build your first agent
- [CLI Quickstart](getting-started/cli-quickstart.md) -- run the autonomous simulation
- [Developer Guide](guide/developer-guide.md) -- comprehensive SDK reference
- [Architecture](guide/architecture.md) -- how Hive works under the hood
