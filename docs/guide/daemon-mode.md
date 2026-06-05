# Daemon Mode

Daemon mode is where Hive becomes an agent OS. Instead of running single tasks, agents persist across cycles, generate their own goals, experience suffering, interact with each other, and live in a simulated economy.

## The Heartbeat Loop

The `HiveDaemon` drives all agents in a shared loop. Each heartbeat (default 10s):

1. Hot-load plugins (every 10 cycles)
2. For each alive agent:
    - Escalate all active stressors
    - Apply suffering effects to Persona behavioral params
    - If agent has an active goal: pursue it via ReAct loop
    - If agent is idle: generate a new goal via ExistenceLoop (or custom GoalStrategy)
    - Log suffering state, emit lifecycle events
3. Auto-kill expired sub-agents
4. Every 5 cycles: swarm learning across agents
5. If economy enabled: process payday and roll life events

## Starting the Daemon

**CLI:**

```bash
hive init
hive start -p coder,gambler,philosopher --heartbeat 10
```

**Python API:**

```python
from hive import Hive

hive = Hive()
hive.init()
hive.spawn("coder")
hive.spawn("gambler")
hive.start(heartbeat=10, cycles=50)
```

## Goal Generation

When an agent has no active goal, the ExistenceLoop generates one by:

1. Checking for scheduled goals due this cycle
2. Checking for pending nudges from users
3. Analyzing the agent's suffering state, peer activity, and recent history
4. Asking the LLM to generate a goal given this context

High `risk_tolerance` prompts ambitious goals. High `social_drive` prompts collaborative goals. Low `concentration` causes more goal switching.

### Custom Goal Strategy

Override goal generation with the `GoalStrategy` protocol:

```python
from hive import GoalStrategy, GoalContext, Goal, HiveDaemon
from uuid import uuid4

class MyStrategy:
    async def generate_goal(self, context: GoalContext) -> Goal | None:
        if context.nudges:
            return Goal(
                goal_id=f"goal-{uuid4().hex[:8]}",
                objective=f"Handle: {context.nudges[0]}",
                reasoning="User nudge",
            )
        return None  # fall through to default

daemon = HiveDaemon(hive_dir=Path(".hive"), goal_strategy=MyStrategy())
```

## Lifecycle Hooks

Register callbacks for daemon events using `HookRegistry`:

```python
daemon.hooks.on("goal_completed", lambda agent_id, goal_id, **kw:
    print(f"{agent_id} completed {goal_id}"))
```

**Available events:**

| Event | Parameters | When |
|-------|-----------|------|
| `cycle_start` | `agent_id`, `cycle_num` | Beginning of each cycle |
| `cycle_end` | `agent_id`, `cycle_num`, `result` | End of each cycle |
| `goal_generated` | `agent_id`, `goal_id`, `objective` | New goal created |
| `goal_completed` | `agent_id`, `goal_id` | Goal finished successfully |
| `goal_abandoned` | `agent_id`, `goal_id` | Goal given up |
| `suffering_changed` | `agent_id`, `suffering_state` | Suffering state updated |

Handlers can be sync or async. Exceptions in handlers are logged but don't crash the daemon.

```python
# Async handler
async def on_suffering(agent_id: str, suffering_state: Any, **kwargs: Any) -> None:
    if suffering_state.cumulative_load > 0.8:
        print(f"WARNING: {agent_id} approaching crisis")

daemon.hooks.on("suffering_changed", on_suffering)

# Remove handler
daemon.hooks.off("suffering_changed", on_suffering)
```

## Human-in-the-Loop Approvals

Some tools should not run without a human's say-so. Enable approvals in
`.hive/config.yaml` and mark which tools are gated:

```yaml
approval:
  enabled: true
  require_for: ["shell_exec", "git_commit"]   # tool names always gated
  auto_approve: []                             # names never gated (overrides flags)
  timeout_cycles: 0                            # auto-deny after N heartbeats (0 = never)
```

A tool can also opt in at definition time with `@tool(requires_approval=True)`.

When a gated tool is called, the agent **parks**: it does not run the tool, an
approval record is persisted, and its status becomes `waiting_approval`. Because
agents are heartbeat-driven records (not live coroutines), the pause survives across
cycles -- each heartbeat the park gate holds the agent cheaply (no model call) until
the request is resolved. The goal stays active throughout.

Resolve from the CLI or the [REST API](rest-api.md#human-in-the-loop-approvals):

```bash
hive approvals                 # list pending requests
hive approve ap-1a2b3c         # let the tool run next cycle
hive deny ap-1a2b3c --reason "too risky"   # agent sees the denial and re-plans
```

An approval is granted for a specific `(tool, arguments)` pair and is single-use:
re-running the same call later prompts again. `timeout_cycles` auto-denies a request
that sits unresolved too long.

## Life Events

The event engine rolls random events each cycle (30% probability). Events force agents to make decisions that affect their stats and suffering.

**Event categories:** career, health, social, financial, random.

**How events work:**

1. Each cycle, `EventEngine.roll_events()` checks for follow-ups and rolls a random event
2. The event is formatted as a prompt with numbered choices
3. The agent's LLM picks a choice
4. Outcomes apply stat effects (money, happiness, reputation) with a luck multiplier (mean 1.0, std 0.25)
5. Some outcomes queue follow-up events for future cycles

**Example event flow:**

```
Event: "A freelance gig appeared paying $200, but it's outside your skill set."
  Choice 1: Take it anyway (risky but rewarding)
  Choice 2: Pass on it (safe but no income)
  Choice 3: Negotiate for training time (balanced)

Agent with high risk_tolerance -> Choice 1
Luck roll: 1.4 (lucky!) -> Earns $280, gains new skill
```

## Agent-to-Agent Protocol (A2A)

Agents communicate via a typed messaging system backed by JSONL files.

**9 message types:**

| Type | Purpose | Auto-reply type |
|------|---------|-----------------|
| REQUEST | Ask for help | RESPONSE |
| RESPONSE | Answer a request | - |
| QUERY | Ask a question | ANSWER |
| ANSWER | Answer a query | - |
| REVIEW | Request peer review | FEEDBACK |
| FEEDBACK | Provide review | - |
| DELEGATE | Assign a task | ACK or REJECT |
| ACK | Accept delegation | - |
| REJECT | Decline with reason | - |

**Collaboration patterns** (pre-built interaction flows):

| Pattern | Description |
|---------|-------------|
| ReviewPattern | Code/work review between two agents |
| MentorPattern | Mentee asks mentor a question |
| DebatePattern | Two agents debate a topic in rounds |
| ChainPattern | Task passes through a chain of agents |
| SwarmTaskPattern | Task broadcast to all agents in parallel |

## Semantic Memory

Agents can store and retrieve memories using TF-IDF similarity search.

```python
from hive.memory.semantic import SemanticMemory

memory = SemanticMemory(hive_dir=Path(".hive"), agent_id="coder")
await memory.store("Learned that the auth module needs refactoring")
results = await memory.search("authentication issues", top_k=5)
```

| Method | Description |
|--------|-------------|
| `store(thought, metadata)` | Store a thought, return memory_id |
| `search(query, top_k=5)` | Find similar memories by TF-IDF |
| `recall(memory_id)` | Retrieve specific memory by ID |
| `forget(memory_id)` | Delete a memory |
| `consolidate(max_age_days, min_access)` | Remove old/unused memories |
| `recent(limit=5)` | Get most recent memories |

Each `MemoryRecord` tracks: `memory_id`, `thought`, `metadata`, `ts`, `access_count`, `last_accessed`.

## Checkpointing

Save and restore agent state snapshots for debugging or recovery.

```python
from hive.checkpoint import CheckpointManager

mgr = CheckpointManager(hive_dir=Path(".hive"))

# Save
cp_id = mgr.save(
    agent_id="coder",
    label="before-risky-change",
    suffering=suffering_state,
    identity=identity,
    ctx=execution_context,
)

# Restore
checkpoint = mgr.restore("coder", cp_id)

# Compare two checkpoints
diff = mgr.diff(checkpoint_a, checkpoint_b)
```

A checkpoint captures: suffering state, active goals, agent identity, world state (balance, job, skills), and persona snapshot.

## Benchmarking

Compare model performance on identical scenarios.

**CLI:**

```bash
hive benchmark --models anthropic:lite,openai:lite,ollama:standard --cycles 5
```

**Python:**

```python
from hive.benchmark.runner import BenchmarkRunner

runner = BenchmarkRunner(hive_dir=Path(".hive"))
result = await runner.run_goal_benchmark(
    models=["anthropic:lite", "openai:lite"],
    cycles=5,
    runs=3,
)
```

Results include: goals completed/abandoned, total tokens, cost, duration, and errors per model.

## HTML Export

Export a recorded run as a standalone HTML report.

**CLI:**

```bash
hive export <run-id> --output report.html
```

**Python:**

```python
from hive.export.html import export_html_report

export_html_report(
    run_id="abc123",
    logs_dir=Path(".hive/logs"),
    output_path=Path("report.html"),
)
```

Reports include agent cards, goal timelines, notepad contents, A2A message threads, and cost tracking. Dark theme, no external dependencies.

## MCP Server

Hive exposes itself as an MCP server so external tools (like Claude Code) can control agents.

```bash
hive-mcp
```

**Exposed tools:** `hive_init`, `hive_start`, `hive_stop`, `hive_status`, `hive_spawn`, `hive_kill`, `hive_nudge`, `hive_logs`, `hive_models`.

Connect from Claude Code or any MCP client by adding to your MCP config:

```json
{
  "mcpServers": {
    "hive": {
      "command": "hive-mcp"
    }
  }
}
```
