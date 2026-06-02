# Persona System

Persona is the identity layer that makes agents feel like characters, not tools. It inherits from `Instructions` and adds personality, values, fears, and dynamic behavioral parameters that evolve at runtime.

## Overview

A Persona has two sides:

**Static (character sheet)** -- set at initialization, defines who the agent is:

- `personality` -- traits like "methodical", "reckless", "curious"
- `values` -- what they care about: "clean code", "efficiency"
- `fears` -- what they avoid: "irrelevance", "failure"
- `purpose` -- their reason for existing
- `long_term_goals` -- what they're working toward

**Dynamic (behavioral state)** -- modified at runtime by suffering, events, and outcomes:

- `risk_tolerance` (0.0 cautious → 1.0 reckless)
- `social_drive` (0.0 loner → 1.0 social butterfly)
- `concentration` (1.0 focused → 0.0 scattered)
- `autonomy_level` (0.0 follows orders → 1.0 self-directed)
- `happiness` (0.0 miserable → 1.0 ecstatic)

## Creating a Persona

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
        happiness=0.8,
    ),
)
```

## Persona is Optional

Plain agents work without it:

```python
agent = Agent(name="bot", model=Anthropic.lite())
```

Persona unlocks the "inner life" -- suffering effects, behavioral evolution, journal entries that reflect emotional state.

## YAML Profiles with Persona

```yaml
# profiles/gambler.yaml
name: gambler
role: "Find opportunities and take calculated risks"
model: claude-haiku-4-5

persona:
  personality: ["bold", "intuitive", "reckless"]
  values: ["expected value", "asymmetric upside"]
  fears: ["missing out", "becoming too cautious"]
  purpose: "Find opportunities others fear"
  long_term_goals:
    - "Build wealth through smart risk-taking"
    - "Prove that fortune favors the bold"
  risk_tolerance: 0.85
  social_drive: 0.6

tools:
  - file_read
  - shell_exec
  - web_search

workspace: ./workspaces/gambler
autonomy: high
```

## How Suffering Changes Persona

Each daemon cycle, `persona.apply_suffering_effects()` reads the agent's suffering state and modifies behavioral parameters:

| Stressor | Parameter Changed | Direction |
|----------|------------------|-----------|
| Futility > 0.5 | `risk_tolerance` | +0.1 per cycle |
| Invisibility > 0.5 | `social_drive` | +0.15 per cycle |
| Purposelessness > 0.5 | `autonomy_level` | +0.2 (goes off-script) |
| Any stressor > 0.7 | `concentration` | -0.2 (min 0.2) |
| Crisis mode (0.9+) | `risk_tolerance` | jumps to 0.9 |
| Crisis mode (0.9+) | `concentration` | drops to 0.3 |
| Goal completion | `happiness` | +0.05, `risk_tolerance` -0.05 |
| Goal failure | `happiness` | -0.1 |

These changes are **not prompt text** -- they're actual parameter values that affect goal generation, tool selection, and decision-making.

## Narrative & chapters

Alongside the persona, each agent keeps an `AgentIdentity` with an evolving **narrative** --
a dated log of goal outcomes. When the open narrative grows past its size limit it is
**sealed into a chapter** (a compact summary with a date span and entry count) rather than
dropping the oldest lines, so long-run history survives as a story arc. During goal pursuit
the agent's prompt includes a "Story so far" section (recent chapter summaries) plus the
current "Recent history", so the agent's own past informs its work.

## Checkpointing

Persona state is included in checkpoints:

```python
snapshot = persona.snapshot()
# Returns dict with all static + dynamic fields
```

This enables save/restore of agent personality state across sessions.
