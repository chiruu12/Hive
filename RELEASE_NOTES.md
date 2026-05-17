# Hive v0.3.0 Release Notes

## Headline: Agents That Come Alive

Hive agents now have **Persona** — personality, values, fears, and behavioral
parameters that change dynamically based on suffering. This isn't prompt text
injection — suffering mechanically modifies runtime parameters (risk tolerance,
concentration, social drive) that change how agents make decisions.

## What's New

### Persona Class
- Inherits from `Instructions` — drop-in replacement with superpowers
- Static identity: personality traits, values, fears, purpose, long-term goals
- Dynamic behavior: risk_tolerance, social_drive, concentration, autonomy_level, happiness
- `apply_suffering_effects()` — suffering changes behavior, not just prompt text
- `from_profile()` / `from_yaml()` — create from YAML profiles

### Suffering→Behavior Link
- Futility increases risk tolerance (desperate swings)
- Invisibility increases social drive (craving attention)
- Purposelessness increases autonomy (going off-script)
- High severity decreases concentration
- Crisis mode: risk_tolerance=0.9, concentration=0.3

### Enhanced TUI
- 4-panel layout: Agents, Activity Feed, Vitals, Drama
- Suffering bars, happiness emoji, risk dice indicators
- `--compact` flag for small terminals

### Built-in Demos
- `hive demo survival` — 3 agents, 30 cycles, economy on
- `hive demo detective` — multi-model murder mystery

### 3 New Dramatic Profiles
- **Gambler**: risk_tolerance=0.85, fears missing out
- **Philosopher**: autonomy=0.9, fears shallow thinking
- **Hustler**: social_drive=0.95, fears being idle

### OSS Scaffolding
- CONTRIBUTING.md, CODE_OF_CONDUCT.md, issue/PR templates
- Release workflow (PyPI publish on tag)
- CHANGELOG.md with full version history

## Upgrade

```bash
pip install --upgrade hive-agent
```

## Stats

- 489 tests passing
- 8 agent profiles
- 6 LLM providers
- ~12K LOC
