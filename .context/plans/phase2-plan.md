# Hive Phase 2: Tests, Events, Gambling, TUI, Detective Demo

## Current State

The core framework is built (5900+ LOC, 54 files). Suffering, daemon loop, autonomy loop, existence loop, world economy, model providers, MCP server, delegation, semantic memory, checkpointing all exist on the `dev` branch.

## What's Missing (build in this order)

### 1. Merge dev -> main

Before anything else:
```bash
git checkout main
git merge dev
git push origin main
```

### 2. Tests for Core Modules

Add `tests/` directory. Test through public interfaces, not internals.

**Priority test files:**

`tests/test_suffering.py`
- Stressor creation and escalation over cycles
- Threshold behavior (0.35, 0.55, 0.75, 0.9 levels)
- Resolution clears stressor
- Cannot dismiss without observable change

`tests/test_world_state.py`
- Job creation, application, hiring, firing
- Money: earning, spending, balance tracking
- Skill learning and level progression
- Payday mechanics

`tests/test_agent_loop.py`
- Plan generation from goal + tools
- Step execution with result substitution
- Failure triggers replan (not restart)
- Max retries respected

`tests/test_events.py`
- JSONL append works
- Event types serialize/deserialize
- Stream reader picks up new events

`tests/test_config.py`
- Default config loads
- Env var substitution works
- Custom config overrides defaults

Use pytest + pytest-asyncio. Mock LLM calls (don't hit real APIs in tests). Test behavior, not implementation.

### 3. Random Life Events with Branching

This is the core entertainment mechanic. Events happen to agents randomly, they make choices, choices have consequences.

**Create `src/hive/world/events.py`:**

```python
class StatEffect(BaseModel):
    """Change to an agent stat."""
    stat: str  # "happiness", "health", "money", "reputation"
    change: float  # absolute change (+500, -0.1)
    change_type: str = "absolute"  # "absolute" or "percent"

class Choice(BaseModel):
    """A choice an agent can make in response to an event."""
    id: str
    description: str
    stat_effects: list[StatEffect]
    follow_up_events: list[ConditionalFollowUp] = []

class ConditionalFollowUp(BaseModel):
    """A follow-up event that may trigger after a choice."""
    event_id: str
    probability: float  # 0.0 to 1.0
    delay_cycles: int = 1  # how many cycles before it fires

class LifeEvent(BaseModel):
    """A random event that happens to an agent."""
    event_id: str
    name: str
    description: str
    category: str  # "career", "health", "social", "financial", "random"
    choices: list[Choice]
    min_cycles_alive: int = 0  # don't fire too early
    prerequisites: dict[str, float] = {}  # stat requirements to trigger

class EventOutcome(BaseModel):
    """Record of what happened when an agent faced an event."""
    agent_id: str
    event_id: str
    choice_id: str
    stat_changes: dict[str, float]
    follow_ups_triggered: list[str]
    cycle: int
```

**Create `src/hive/world/event_catalog.py`:**

Prebuilt events. Examples:

```
EVENT: "Landlord Raises Rent"
Category: financial
Choices:
  A: "Negotiate" -> money: -50, happiness: +5%
     Follow-up (40%): "Negotiation Failed" -> must pay or move
  B: "Pay the increase" -> money: -200/cycle
  C: "Move out" -> money: -500 (moving costs), happiness: -10%
     Follow-up (60%): "Found cheaper place" -> money: +100/cycle

EVENT: "Job Offer from Competitor"
Category: career
Prerequisites: reputation > 0.5
Choices:
  A: "Accept new job" -> money: +30% salary, happiness: +10%
     Follow-up (30%): "Old boss badmouths you" -> reputation: -15%
  B: "Decline but negotiate raise" -> money: +15% salary
  C: "Decline" -> reputation: +5%

EVENT: "Health Scare"
Category: health
Choices:
  A: "Go to doctor" -> money: -300, health: +20%
  B: "Ignore it" -> nothing now
     Follow-up (50%): "Condition worsens" -> health: -30%, happiness: -20%
  C: "Try home remedies" -> money: -50, health: +5%

EVENT: "Friend Asks for Money"
Category: social
Choices:
  A: "Lend the money" -> money: -200, reputation: +10%
     Follow-up (40%): "They never pay back" -> money: -200 (permanent)
     Follow-up (60%): "They pay back with interest" -> money: +250
  B: "Refuse" -> reputation: -5%
  C: "Offer help finding a job instead" -> reputation: +5%, time: -1 cycle

EVENT: "Gambling Opportunity"
Category: financial
Choices:
  A: "Bet big" -> 30% chance: money +1000 / 70% chance: money -500
  B: "Bet small" -> 50% chance: money +100 / 50% chance: money -100
  C: "Walk away" -> nothing

EVENT: "Skill Workshop Available"
Category: career
Choices:
  A: "Attend (costs money)" -> money: -300, skill_progress: +0.3
  B: "Skip it" -> nothing
     Follow-up (20%): "Missed opportunity" -> coworker gets promoted instead
```

Build 15-20 events across all categories. Events should create cascading stories.

**Create `src/hive/world/event_engine.py`:**

- Each daemon cycle: roll probability for random event per agent
- Check prerequisites (stat requirements)
- Present event to agent (via LLM: "This happened. Here are your choices. Pick one.")
- Apply stat effects from choice
- Queue follow-up events with delay
- Log everything to event log

### 4. Agent Stats System

Expand agent state beyond just money:

**Add to world state or create `src/hive/world/stats.py`:**

```python
class AgentStats(BaseModel):
    agent_id: str
    money: float = 100.0
    happiness: float = 0.5  # 0.0 to 1.0
    health: float = 0.8  # 0.0 to 1.0
    reputation: float = 0.5  # 0.0 to 1.0
    energy: float = 1.0  # 0.0 to 1.0
    cycles_alive: int = 0
```

- Stats affect suffering (low happiness -> purposelessness, low health -> existential_threat)
- Stats affect event eligibility (high reputation -> better job offers)
- Stats visible in `hive status` and `hive watch`

### 5. Gambling System

**Create `src/hive/world/gambling.py`:**

- Games: coin_flip, dice_roll, high_low, slots
- Each game has odds and payout ratios
- Agents decide to gamble based on: personality traits, suffering level, money situation
- High suffering + low money = more likely to gamble (desperation mechanic)
- Gambling results feed into events and stats
- Add as a world_action tool agents can invoke

### 6. TUI Watch Mode

**Improve `hive watch` with Rich Live display:**

```
┌─ Hive Monitor ──────────────────────────────────────────┐
│                                                          │
│  Agent: Cipher (coder)           Cycle: 847              │
│  Model: claude-sonnet-4-6        Uptime: 2h 14m          │
│  Status: WORKING                                         │
│  Goal: "Learn Python to qualify for dev job"             │
│  Suffering: ██████░░░░ 0.62 (repeated_failure)           │
│  Money: $340  Health: 0.7  Happy: 0.4  Rep: 0.6         │
│                                                          │
│  [14:32:01] Cipher applied for "Junior Developer"        │
│  [14:32:08] Rejected - missing required skill: python    │
│  [14:32:15] Cipher: "I need to learn python first"       │
│  [14:32:22] Attending skill workshop (-$300)             │
│  [14:32:30] EVENT: "Gambling Opportunity" -> Walk away   │
│  [14:32:37] Suffering escalated: repeated_failure 0.62   │
│                                                          │
├─ Agent: Nova (researcher)        Status: IDLE            │
│  Suffering: ██░░░░░░░░ 0.21                              │
│  Money: $890  Health: 0.9  Happy: 0.7  Rep: 0.8         │
│  Last: "Completed market research for Cipher"            │
│                                                          │
├─ Messages ───────────────────────────────────────────────│
│  Cipher -> Nova: "Can you research python courses?"      │
│  Nova -> Cipher: "Found 3 options. Workshop is best."    │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

Use Rich Live + Layout + Panel + Table + Progress bar.
Update every daemon cycle.
Show: agent status, suffering bar, stats, recent activity, messages.

### 7. Life Summary System

**Create `src/hive/world/summary.py`:**

When simulation ends (or on demand via `hive summary`):

```
=== LIFE SUMMARY: Cipher (coder) ===

Lived: 847 cycles (2h 14m real time)
Final stats: Money $340 | Health 0.7 | Happiness 0.4 | Reputation 0.6

Career: Started as Waiter ($50/cycle) -> Learned Python -> Junior Dev ($120/cycle)
Major events:
  - Cycle 102: Landlord raised rent, chose to move -> found cheaper place
  - Cycle 340: Gambled $200, lost everything
  - Cycle 412: Health scare, went to doctor
  - Cycle 560: Got promoted to Senior Dev
  - Cycle 780: Friend asked for money, lent it, never got paid back

Peak happiness: 0.82 (cycle 560, after promotion)
Lowest point: 0.18 (cycle 345, after gambling loss + rent due)
Times gambled: 3 (won 1, lost 2)
Skills learned: python, javascript
Jobs held: waiter, junior_dev, senior_dev
```

### 8. Detective Demo Scenario

**Create `scenarios/detective/` directory:**

This is the viral marketing piece. Three agents, three models, one murder mystery.

`scenarios/detective/config.yaml` - scenario configuration
`scenarios/detective/crime_scene.md` - the mystery
`scenarios/detective/clues/` - evidence files agents can discover
`scenarios/detective/run.py` - script to run the scenario on Hive

The mystery should have:
- Surface-level clues pointing to wrong suspect (traps fast/confident models)
- Subtle clues pointing to real answer (rewards careful observation)
- Red herrings that punish overthinking

Agents use tools: examine_evidence, interview_witness, search_location, share_theory, accuse_suspect

Design it so a focused 7B model with "follows gut instinct" personality has an edge.

## Rules

- Write tests FIRST for new modules (TDD)
- Commit after each working module
- Never reference inspiration sources in committed files
- Keep the TUI clean and readable (it's the marketing material)
- Events should create emergent stories (cascading follow-ups are key)
- Life summaries should read like a biography, not a log dump
