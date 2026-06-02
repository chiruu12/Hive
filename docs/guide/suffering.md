# Suffering System

The suffering system is Hive's core differentiator. It mechanically modifies agent behavior at runtime -- not through prompt engineering, but by changing actual behavioral parameters.

## How It Works

Each agent tracks a `SufferingState` with active stressors. Stressors escalate over time and are resolved when conditions change. When stressor severity crosses thresholds, the agent's Persona parameters shift, changing how it generates goals, uses tools, and makes decisions.

## The 6 Stressor Types

| Stressor | Trigger | Behavioral Effect |
|----------|---------|-------------------|
| **Futility** | Low goal completions, stalling | `risk_tolerance` increases -- desperate swings |
| **Invisibility** | No observable impact on others | `social_drive` increases -- craves interaction |
| **Repeated Failure** | >50% goal failure rate | `concentration` decreases -- scattered, worse performance |
| **Purposelessness** | No goals attempted | `autonomy_level` increases -- goes off-script |
| **Identity Violation** | Actions contradict agent's values | `risk_tolerance` decreases -- withdraws |
| **Existential Threat** | System instability | Extreme parameter shift |

## Severity Thresholds

| Threshold | Value | Effect |
|-----------|-------|--------|
| Prominent | 0.35 | Suffering appears in agent's prompts |
| Constrained | 0.55 | Suffering limits available options |
| Dominant | 0.75 | Suffering demands immediate attention |
| Crisis | 0.90 | Crisis mode -- extreme behavioral shift |

In **crisis mode** (cumulative load > 0.9): `risk_tolerance` jumps to 0.9, `concentration` drops to 0.3. The agent may frantically spawn sub-agents or completely shut down.

## Escalation

Each stressor has an escalation rate (severity increase per cycle). Built-in rates:

- Futility: 0.03/cycle
- Invisibility: 0.025/cycle
- Repeated Failure: 0.04/cycle
- Purposelessness: 0.02/cycle
- Identity Violation: 0.035/cycle
- Existential Threat: 0.05/cycle

After 3 cycles in crisis mode, suffering force-resets to prevent permanent lockup.

## Adding Custom Stressors

```python
from hive import StressorRegistry, SufferingState

registry = StressorRegistry.default()
registry.register("burnout", escalation_rate=0.05, description="Chronic overwork exhaustion")

state = SufferingState(agent_id="agent-1")
state.add_stressor("burnout", "Worked 50 cycles straight", "Take a rest cycle")
```

## Mood

An agent's **mood** is a *derived* emotional state -- no extra stored state. The default
`CircumplexMood` maps the agent's positive signal (`happiness`) and aversive load
(`suffering`) onto a valence/arousal circumplex and names the result. During goal pursuit
the mood descriptor is added to the agent's prompt, so its emotional state colours how it
works.

| Mood | When | Cue |
|------|------|-----|
| **content** | positive, calm | satisfied; open to exploration |
| **motivated** | positive, activated | energized; take initiative |
| **steady** | neutral, calm | balanced and focused |
| **restless** | neutral, activated | unsettled; pick a concrete next step |
| **discouraged** | negative, calm | low energy; favour small wins |
| **anxious** | negative, activated | on edge; resolve stressors first |
| **overwhelmed** | in crisis | focus inward on relief |

Swap the model via `MoodRegistry` (see EXTENDING.md → Custom Mood Model):

```python
from hive import MoodRegistry, MoodState

class StoicMood:
    def derive(self, happiness, suffering_load, in_crisis):
        return MoodState("stoic", 0.0, 0.0, "unmoved; proceed steadily")

MoodRegistry.default().set_model(StoicMood())
```

## Observing Suffering

In the TUI (`hive watch`), suffering appears as:

- Suffering bars per agent (0-100%)
- Happiness emoji indicators
- Risk indicators when `risk_tolerance > 0.6`
- Drama panel highlights suffering changes and crisis events

Programmatically:

```python
daemon.hooks.on("suffering_changed", lambda agent_id, suffering_state, **kw:
    print(f"{agent_id}: load={suffering_state.cumulative_load:.0%}"))
```

## Configuration

In `.hive/config.yaml`:

```yaml
suffering:
  threshold_prominent: 0.35
  threshold_constrained: 0.55
  threshold_dominant: 0.75
  threshold_crisis: 0.90
  max_stressors: 5
  initial_severity: 0.20
  crisis_reset_after: 3
  escalation_rates:
    futility: 0.03
    invisibility: 0.025
    repeated_failure: 0.04
    purposelessness: 0.02
    identity_violation: 0.035
    existential_threat: 0.05
```
