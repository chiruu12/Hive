# Hive Development

## Project Overview

Hive is a local-first agent operating system. Users spawn persistent AI agents via CLI that collaborate, write code, and use tools autonomously. Config-driven with YAML agent profiles, multi-model support (Anthropic, OpenAI, Fireworks, Ollama, LM Studio), and built-in safety via workspace isolation.

## Architecture

```
src/hive/
├── cli/              # Typer CLI (commands map 1:1 to user actions)
├── daemon/           # Background service (lifecycle, heartbeat loop, diagnostics)
├── agents/           # Agent profiles, state, suffering, identity, delegation
├── runtime/          # Standalone agent framework (ReAct loop, tools)
├── memory/           # Persistence (SQLite store, JSONL events, semantic memory)
├── models/           # Model providers (Anthropic, OpenAI, Groq, etc.), registry, factory
├── interactions/     # Multi-agent interaction patterns (round-table, pairs, freeform)
├── world/            # Simulated economy (jobs, skills, finances, life events)
├── logging/          # Structured run logs (decisions, tools, goals, suffering)
├── mcp/              # MCP client and server
├── checkpoint.py     # Save/restore agent state snapshots
├── api.py            # Programmatic Python API (Hive facade class)
└── config.py         # Config loading (YAML + env vars)
```

## Tech Stack

- **Language**: Python 3.11+
- **CLI**: Typer + Rich (terminal UI)
- **Async**: asyncio (concurrent agent execution)
- **Database**: SQLite via aiosqlite
- **LLM**: anthropic SDK, OpenAI SDK (also for Fireworks, Ollama, LM Studio)
- **Packaging**: uv, pyproject.toml
- **Testing**: pytest + pytest-asyncio

## Code Conventions

### Architecture Principles

- **Config-driven**: Agent behavior defined in YAML, not hardcoded
- **OOP for entities**: Agent, Task, Room, Tool are classes with clear interfaces
- **FP for data transforms**: Pure functions for parsing, routing, formatting
- **Protocol classes**: Use Python Protocols for model providers, tool executors
- **Dependency injection**: Components receive dependencies, don't create them
- **Single responsibility**: Each module does one thing well

### File Organization

- One class per file when the class is substantial (>100 lines)
- Related small classes can share a file
- Prefix private modules with underscore only if truly internal
- Tests mirror src structure: `tests/runtime/test_agent.py` tests `src/hive/runtime/agent.py`

### Naming

- Classes: PascalCase (`AgentLoop`, `ModelRouter`, `ToolRegistry`)
- Functions/methods: snake_case (`spawn_agent`, `execute_step`)
- Constants: UPPER_SNAKE (`MAX_STEPS`, `DEFAULT_MODEL`)
- Files: snake_case (`agent_loop.py`, `model_router.py`)
- Agent profiles: kebab-case YAML files (`code-reviewer.yaml`)

### Type Hints

- All public functions must have full type annotations
- Use `TypedDict` for structured dicts passed between modules
- Use `Protocol` for interfaces (model providers, executors)
- Use `dataclass` or `pydantic.BaseModel` for data objects

### Error Handling

- Never catch bare `Exception` unless re-raising
- Agent failures don't crash the daemon (isolated per-agent error handling)
- Log errors with context (agent_id, task_id, step number)

### Testing

- Unit tests for pure functions and data transforms
- Integration tests for agent loop with mocked LLM
- No mocking of internal modules (test through public interfaces)
- Fixtures for common setups (agent with profile, task with steps)

## Key Design Decisions

1. **Agents are records, not processes.** The daemon drives agent execution. Agents don't run independently.
2. **Tools are Toolkit classes.** Extend `Toolkit`, decorate methods with `@tool()`. JSON Schema extracted from type hints.
3. **YAML profiles define agents.** Role, model, tools, autonomy level, system prompt. No code needed to create an agent.
4. **Event log is immutable.** JSONL append-only. Enables replay, debugging, and recovery.
5. **Model router is pluggable.** Protocol-based. Add new providers without changing agent code.
6. **Plugins extend toolkits.** Drop a Python file in `.hive/plugins/` with a Toolkit subclass -- auto-discovered.
7. **Daemon is hookable.** `HookRegistry` emits lifecycle events (cycle_start/end, goal_completed/abandoned/generated, suffering_changed). Register callbacks via `daemon.hooks.on()`.
8. **Registries over hardcoded lists.** `StressorRegistry` for suffering types, `PatternRegistry` for A2A patterns, `InteractionPatternRegistry` for scenario patterns, `MemoryStrategyRegistry` for memory strategies.
9. **Goal generation is pluggable.** `GoalStrategy` protocol -- implement `generate_goal(GoalContext)` and pass to `HiveDaemon(goal_strategy=...)` to override `ExistenceLoop`.

## Extension Points

| Extension | API | File |
|-----------|-----|------|
| Custom tool | Subclass `Toolkit`, `@tool()` methods | `src/hive/tools/base.py` |
| Custom model provider | Subclass `BaseProvider` | `src/hive/models/base.py` |
| Custom stressor | `StressorRegistry.default().register(name, rate, desc)` | `src/hive/agents/suffering.py` |
| Custom A2A pattern | Subclass `A2APattern`, `PatternRegistry.default().register(name, instance)` | `src/hive/interactions/registry.py` |
| Custom goal strategy | Implement `GoalStrategy` protocol, pass to `HiveDaemon` | `src/hive/agents/goal_strategy.py` |
| Daemon hooks | `daemon.hooks.on("event", callback)` | `src/hive/daemon/hooks.py` |
| Agent profile | YAML in `profiles/` | `src/hive/agents/profile.py` |
| Plugin toolkit | Drop in `.hive/plugins/` | `src/hive/runtime/plugin_loader.py` |
| Custom STT provider | Implement `STTProvider` protocol | `src/hive/stt/base.py` |
| Custom trigger | Implement `Trigger` protocol | `src/hive/triggers/base.py` |
| Intent routing | `IntentRouter(model, intents)` | `src/hive/routing/router.py` |

See `EXTENDING.md` for copy-paste code examples for each extension point.

## Commands

```bash
# Development
uv run pytest                    # Run tests
uv run pytest tests/runtime/     # Run specific test module
uv run python -m hive.cli        # Run CLI locally
uv run ruff check src/           # Lint
uv run ruff format src/          # Format
uv run mypy src/                 # Type check

# All checks
uv run pytest && uv run ruff check src/ && uv run mypy src/
```

## Adding a New Tool

1. Create a `Toolkit` subclass in `src/hive/runtime/toolkits.py` (or a plugin file)
2. Decorate methods with `@tool()` -- JSON Schema auto-extracted from type hints
3. Instantiate in `daemon/loop.py:_build_toolkits()` or drop in `.hive/plugins/`

## Adding a New Model Provider

1. Subclass `BaseProvider` from `src/hive/models/base.py` in a new file under `src/hive/models/`
2. Implement `.lite()`, `.standard()`, `.pro()` tier classmethods
3. Add routing logic in `src/hive/models/factory.py` (`create_runtime_provider()`)
4. Add model entries to `models.yaml`

## Adding a New Agent Preset

1. Create YAML file in `profiles/`
2. Define: name, role, model, tools, autonomy, system_prompt
3. It's immediately available via `hive spawn <name>`

## Documentation

The docs site lives in `docs/` and is built with MkDocs + Material theme.

### Documentation Rules

**When making code changes, update docs in the same PR:**

- **New toolkit**: Add to `docs/guide/toolkits.md` with tool table and usage example
- **New CLI command**: Add to `docs/guide/cli-reference.md` with flags and examples
- **New model provider**: Add to provider table in `docs/index.md` and `docs/api/python-api.md`
- **New agent profile**: Add to profiles table in `docs/index.md`
- **New extension point**: Add to `docs/extending/index.md` with copy-paste example and test
- **Changed API (Agent, Hive, Persona, etc.)**: Update `docs/api/python-api.md` and `docs/api/sdk-reference.md`
- **Changed daemon behavior**: Update `docs/guide/daemon-mode.md`
- **Changed suffering/persona mechanics**: Update `docs/guide/suffering.md` or `docs/guide/persona.md`
- **New config option**: Add to config table in `docs/getting-started/cli-quickstart.md` and `docs/guide/architecture.md`

### Style

- Use `--` (double hyphen) not em dashes
- Code examples must be runnable -- no pseudocode
- Tables for API references, prose for concepts
- Keep pages focused -- one topic per page

### Building

```bash
uv run mkdocs build --strict   # Build and check for errors
uv run mkdocs serve            # Local preview at localhost:8000
```

Docs auto-deploy to GitHub Pages on push to main via `.github/workflows/docs.yml`.
