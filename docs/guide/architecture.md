# Architecture

Hive is a local-first autonomous agent OS. Agents are persistent entities driven by a daemon heartbeat loop, with tools, memory, suffering, and multi-model support.

## Directory Structure

```
src/hive/
├── cli/              # Typer CLI -- commands map 1:1 to user actions
├── daemon/           # Background service
│   ├── loop.py       # HiveDaemon -- heartbeat loop driving all agents
│   ├── hooks.py      # HookRegistry -- lifecycle event callbacks
│   ├── lifecycle.py  # Agent spawning and killing
│   ├── diagnostics.py# Health checks and status reporting
│   └── setup.py      # Hive directory initialization
├── agents/           # Agent state and behavior
│   ├── profile.py    # AgentProfile -- YAML-driven configuration
│   ├── state.py      # AgentState, AgentStatus enum
│   ├── existence.py  # ExistenceLoop -- autonomous goal generation
│   ├── goal_strategy.py # GoalStrategy protocol, GoalContext, Goal
│   ├── suffering.py  # SufferingState, StressorRegistry, stressor types
│   ├── identity.py   # IdentityManager -- narrative and opinions
│   ├── delegation.py # DelegationEngine -- inter-agent task routing
│   ├── specialization.py # SpecializationTracker -- task expertise
│   └── swarm.py      # SwarmLearning -- cross-agent pattern discovery
├── runtime/          # Agent execution framework
│   ├── agent.py      # Agent -- ReAct loop with tools
│   ├── persona.py    # Persona -- dynamic personality that evolves
│   ├── types.py      # Message, ToolCall, ToolResult, GenerateResult
│   ├── instructions.py # Instructions base class
│   ├── workflow.py   # Workflow -- multi-step task execution
│   └── plugin_loader.py # Hot-load Toolkit subclasses from plugins/
├── models/           # LLM provider implementations
│   ├── base.py       # BaseProvider ABC
│   ├── factory.py    # create_runtime_provider() -- routes model names
│   ├── registry.py   # ModelRegistry -- models.yaml loader
│   ├── anthropic.py  # Anthropic provider (Claude)
│   ├── openai.py     # OpenAI provider
│   ├── fireworks.py  # Fireworks provider
│   ├── groq.py       # Groq provider
│   ├── ollama.py     # Ollama provider (local)
│   └── lmstudio.py   # LM Studio provider (local)
├── interactions/     # Multi-agent protocols
│   ├── a2a.py        # A2AStore, A2AMessage, A2AMessageType
│   ├── a2a_patterns.py # A2APattern ABC + 5 built-in patterns
│   ├── registry.py   # PatternRegistry, InteractionPatternRegistry
│   ├── base.py       # Participant protocol, InteractionPattern ABC
│   ├── exchange.py   # ExchangeRunner -- lightweight orchestrator
│   ├── runner.py     # ScenarioRunner -- end-to-end scenario execution
│   ├── presets.py    # Pre-built ExchangeConfig factories
│   └── patterns/     # round_table, pairs, freeform
├── memory/           # Persistence layer
│   ├── store.py      # HiveStore -- SQLite via aiosqlite
│   ├── events.py     # EventLog -- JSONL append-only event stream
│   ├── semantic.py   # SemanticMemory -- TF-IDF similarity search
│   └── goals.py      # GoalEngine -- hierarchy and priority
├── tools/            # 15 toolkit modules
│   ├── base.py       # Toolkit, Tool, @tool() decorator
│   └── */toolkit.py  # a2a, comms, delegation, file, git, mcp, memory,
│                     #   notepad, schedule, shell, sub_agents, web, world
├── world/            # Simulated economy
│   ├── state.py      # WorldState -- money, jobs, skills
│   ├── event_engine.py # Random life events
│   └── stats.py      # StatsManager
├── logging/          # Structured run logs
│   ├── models.py     # CycleLog, GoalLog, SufferingLog, DecisionLog
│   └── writer.py     # LogWriter -- writes to logs directory
├── mcp/              # MCP client and server
├── checkpoint.py     # Save/restore agent state snapshots
├── api.py            # Hive facade class -- programmatic Python API
└── config.py         # HiveConfig -- YAML + env var loading
```

## Core Classes

| Class | File | Purpose | Key Methods |
|-------|------|---------|-------------|
| `Agent` | `runtime/agent.py` | ReAct loop agent with tools | `run()`, `run_once()`, `run_once_structured()` |
| `Persona` | `runtime/persona.py` | Dynamic personality with suffering effects | `build_system_prompt()`, `apply_suffering_effects()`, `snapshot()` |
| `HiveDaemon` | `daemon/loop.py` | Heartbeat loop driving all agents | `start()`, `hooks` property |
| `HookRegistry` | `daemon/hooks.py` | Event bus for lifecycle callbacks | `on()`, `off()`, `emit()` |
| `ExistenceLoop` | `agents/existence.py` | Autonomous goal generation | `generate_goal()`, `generate_goal_from_context()` |
| `GoalStrategy` | `agents/goal_strategy.py` | Protocol for pluggable goal gen | `generate_goal(context)` |
| `SufferingState` | `agents/suffering.py` | Per-agent suffering tracking | `add_stressor()`, `escalate_all()`, `resolve()` |
| `StressorRegistry` | `agents/suffering.py` | Extensible stressor types | `register()`, `get()`, `all_types()` |
| `AgentProfile` | `agents/profile.py` | YAML-driven agent configuration | `build_system_prompt()` |
| `Toolkit` | `tools/base.py` | Base class for tool groups | `get_tools()`, `bind()` |
| `Tool` | `tools/base.py` | Single callable tool | `call()`, `to_schema()` |
| `BaseProvider` | `models/base.py` | LLM provider ABC | `generate()`, `generate_with_metadata()`, `generate_structured()` |
| `PatternRegistry` | `interactions/registry.py` | A2A pattern registry | `register()`, `get()`, `list_patterns()` |
| `A2APattern` | `interactions/a2a_patterns.py` | Collaboration pattern ABC | `execute()` |
| `A2AStore` | `interactions/a2a.py` | Agent-to-agent message store | `send()`, `get_inbox()`, `get_pending_requests()` |
| `HiveStore` | `memory/store.py` | SQLite persistence | `save_goal()`, `complete_goal()`, `list_agents()` |
| `EventLog` | `memory/events.py` | JSONL event stream | `append()` |

## Performance and Persistence Notes

- **Concurrent tool execution.** When a model turn emits several tool calls, the
  `Agent` runs them concurrently (`asyncio.gather`) rather than one at a time, so a
  turn's wall-time tracks the slowest tool instead of their sum. Each call is isolated
  -- a raised exception or unknown tool name becomes an error result for that call
  without affecting its siblings -- and results are appended to the conversation in the
  original call order so transcripts stay deterministic.
- **Concurrent agent cycles.** Each heartbeat runs alive agents' cycles concurrently
  with bounded concurrency (`max_concurrent_agents`, a semaphore). Every cycle is
  isolated -- its own timeout and error handling -- so one slow, timed-out, or failing
  agent never blocks or breaks the others that heartbeat. Set `max_concurrent_agents: 1`
  for fully sequential behavior. Each agent's provider and profile are cached across
  cycles (rebuilt only when the model changes or the profile YAML's mtime changes),
  alongside the existing per-agent memory and persona caches.
- **Tool discovery is cached.** A `Toolkit` discovers its `@tool` methods once (at
  `bind()` or first `get_tools()`) and reuses the result; `rebind()` swaps the agent id
  without rebuilding the cache (a copy resets the cache so a clone binds to itself).
- **Indexed, versioned SQLite.** `HiveStore` indexes hot lookup columns
  (`agent_id`, `status`, `fire_at`, `parent_goal_id`, ...) and tracks its schema with
  SQLite's `PRAGMA user_version`. Schema changes are ordered migration steps applied in
  a single transaction on `initialize()`, so an older database upgrades in place without
  data loss.
- **WAL journaling + cascades.** The store runs in WAL mode (set once on `initialize()`,
  persistent in the DB header) with a 5s busy timeout, so readers and a writer don't lock
  each other out across concurrent agent cycles or other processes (the MCP server, the
  CLI). Child tables (`sessions`, `goals`, `tasks`, ...) declare `ON DELETE CASCADE` on
  their foreign key to `agents`, so `HiveStore.delete_agent()` removes an agent and all
  of its rows together. FK enforcement is opt-in per operation, so writing child rows for
  a standalone agent that was never persisted to `agents` still works.
- **Crash-durable event log.** The JSONL session log is append-only by construction.
  Setting `event_log_fsync: true` (env `HIVE_EVENT_LOG_FSYNC`) flushes and `fsync()`s
  every append so an acknowledged event survives a power/OS crash; it defaults to off
  because that is one `fsync` per event on the hot write path. Readers tolerate a torn
  last line from an interrupted append.
- **Deterministic mode.** Setting `seed` (env `HIVE_SEED`) gives the stochastic world
  layer reproducible RNG streams: the daemon injects a seeded `random.Random` into
  `EventEngine` (event rolls, luck, follow-ups) and a separately-derived one into
  `WorldState` (gambling), so one subsystem's draws don't perturb the other. Each run
  writes a `manifest.json` (`logs/runs/<run-id>/`) with the hive version, seed, model
  config, and spawned agents. The seed governs the world RNG only -- LLM outputs are not
  deterministic -- so the manifest, not bit-for-bit replay, is what makes a run reproducible.

## Extension Points

| What | How | File | Example |
|------|-----|------|---------|
| Custom tool | Subclass `Toolkit`, decorate methods with `@tool()` | `tools/base.py` | See EXTENDING.md |
| Custom model provider | Subclass `BaseProvider` | `models/base.py` | See EXTENDING.md |
| Custom stressor | `StressorRegistry.default().register(...)` | `agents/suffering.py` | See EXTENDING.md |
| Custom A2A pattern | Subclass `A2APattern`, register via `PatternRegistry` | `interactions/registry.py` | See EXTENDING.md |
| Custom world content | `EventRegistry`/`JobRegistry` `.default().register(...)` | `world/registry.py` | See EXTENDING.md |
| Custom goal strategy | Implement `GoalStrategy` protocol | `agents/goal_strategy.py` | See EXTENDING.md |
| Daemon hooks | `daemon.hooks.on("event", callback)` | `daemon/hooks.py` | See EXTENDING.md |
| Custom agent profile | YAML file in `profiles/` | `agents/profile.py` | See EXTENDING.md |
| Plugin toolkit | Drop Toolkit subclass in `.hive/plugins/` | `runtime/plugin_loader.py` | See EXTENDING.md |

## Data Flow -- Daemon Cycle

```
Each heartbeat (default 10s):
  1. Hot-load plugins (every 10 cycles)
  2. For each alive agent (run concurrently, bounded by max_concurrent_agents;
     each cycle isolated so one slow/failing agent never blocks the others):
     a. emit("cycle_start")
     b. Escalate all stressors
     c. Load profile, identity, persona, memory
     d. Apply suffering → persona behavioral effects
     e. If active goal:
        - Pursue goal via Agent ReAct loop
        - Assess conditions (fire/resolve stressors)
        - On success: emit("goal_completed"), checkpoint, update narrative
        - On failure: emit("goal_abandoned"), update narrative, record stressor
     f. If idle:
        - Check scheduled goals
        - Generate a goal (custom GoalStrategy or ExistenceLoop). The prompt
          includes the agent's stats (health/energy/happiness/reputation) so a
          drained or unwell agent steers toward recovery (D1)
        - emit("goal_generated")
     g. Log suffering state
     h. emit("suffering_changed")
     i. emit("cycle_end")
  3. Auto-kill expired sub-agents
  4. Every 5 cycles: swarm learning
  5. If economy: process payday + life events. A life-event Choice may declare a
     `stressor` it causes or `resolves_stressor` it relieves -- the daemon feeds
     these into the agent's suffering, and records the event in its narrative (D1)
  6. Sleep heartbeat seconds
```

**Feedback loops (D1).** The world, suffering, goals, and identity influence each
other: life events add/resolve stressors and append to the narrative; agent stats
feed goal generation; and both goal *and* event outcomes shape the agent's story.

## Configuration

All config lives in `.hive/config.yaml` and env vars.

| Section | Key | Type | Default | Description |
|---------|-----|------|---------|-------------|
| `suffering` | `threshold_prominent` | `float` | `0.35` | Show suffering in prompts |
| `suffering` | `threshold_constrained` | `float` | `0.55` | Suffering limits options |
| `suffering` | `threshold_dominant` | `float` | `0.75` | Suffering demands attention |
| `suffering` | `threshold_crisis` | `float` | `0.90` | Crisis mode threshold |
| `suffering` | `max_stressors` | `int` | `5` | Max concurrent stressors |
| `suffering` | `initial_severity` | `float` | `0.20` | Starting severity for new stressors |
| `suffering` | `crisis_reset_after` | `int` | `3` | Cycles in crisis before force reset |
| `suffering` | `escalation_rates` | `dict[str,float]` | Per-type | Daily escalation rate per stressor |
| `economy` | `enabled` | `bool` | `true` | Enable economy simulation |
| `economy` | `starting_balance` | `float` | `100.0` | Initial agent balance |
| `economy` | `skill_course_cost` | `float` | `80.0` | Cost to learn a skill |
| `economy` | `learnable_skills` | `list[str]` | 6 skills | Available skills to learn |
| `daemon` | `heartbeat` | `int` | `10` | Seconds between cycles |
| `daemon` | `max_retries` | `int` | `2` | Retries on agent failure |
| `daemon` | `cycle_timeout` | `int` | `300` | Per-agent cycle timeout in seconds (0 = none) |
| `daemon` | `max_concurrent_agents` | `int` | `8` | Max agent cycles run concurrently per heartbeat |
| `daemon` | `tool_timeout` | `float` | `60.0` | Per-tool wall-clock limit in seconds (0 = none); a hung tool becomes a tool-error instead of stalling the cycle |
| `model` | `default_model` | `str` | `claude-haiku-4-5` | Default LLM model |
| `model` | `planning_model` | `str` | `claude-sonnet-4-6` | Model for planning tasks |
| `model` | `max_tokens` | `int` | `4096` | Max generation tokens |
| `model` | `temperature` | `float` | `0.0` | Generation temperature |
| `tools` | `shell_pass_env` | `bool` | `false` | Pass secrets (API keys, tokens) to agent shell commands; scrubbed by default |
| `tools` | `shell_allow_dev_commands` | `bool` | `true` | Allow python/git/curl etc. in the restricted shell (these can escape the workspace jail) |
| `tools` | `file_max_read_bytes` | `int` | `10000000` | Refuse file reads larger than this |
| `tools` | `file_max_write_bytes` | `int` | `10000000` | Refuse file writes larger than this |
| `plugins` | `enabled` | `bool` | `true` | Load plugin toolkits from `.hive/plugins/` |
| `plugins` | `allowlist` | `list[str]` | `[]` | Only load these plugin filenames/stems; empty = all |
| `retention` | `enabled` | `bool` | `false` | Periodically delete terminal rows (resolved approvals, fired alarms, delivered nudges, finished sessions/delegations) and deny dead agents' pending approvals |
| `retention` | `days` | `int` | `30` | Only rows older than this are deleted |
| `retention` | `interval_cycles` | `int` | `100` | Run the janitor every N heartbeats |

Env var overrides: `HIVE_HEARTBEAT`, `HIVE_DEFAULT_MODEL`, `HIVE_STARTING_BALANCE`, etc.
