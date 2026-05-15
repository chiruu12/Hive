# Hive Development

## Project Overview

Hive is a local-first agent operating system. Users spawn persistent AI agents via CLI that collaborate, write code, and use tools autonomously. Config-driven with YAML agent profiles, multi-model support (Anthropic, OpenAI, Fireworks, Ollama, LM Studio), and built-in safety via workspace isolation.

## Architecture

```
src/hive/
├── cli/              # Typer CLI (commands map 1:1 to user actions)
├── daemon/           # Background service (lifecycle, heartbeat loop, diagnostics)
├── agents/           # Agent profiles, state, suffering, identity, delegation
├── runtime/          # Standalone agent framework (ReAct loop, tools, providers)
├── memory/           # Persistence (SQLite store, JSONL events, semantic memory)
├── models/           # Model registry (YAML catalog, router, cost estimation)
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
6. **Plugins extend toolkits.** Drop a Python file in `.hive/plugins/` with a Toolkit subclass — auto-discovered.

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
2. Decorate methods with `@tool()` — JSON Schema auto-extracted from type hints
3. Instantiate in `daemon/loop.py:_build_toolkits()` or drop in `.hive/plugins/`

## Adding a New Model Provider

1. Implement `RuntimeProvider` protocol in `src/hive/runtime/providers.py`
2. Add routing logic in `create_runtime_provider()` factory
3. Add model entries to `models.yaml`

## Adding a New Agent Preset

1. Create YAML file in `profiles/`
2. Define: name, role, model, tools, autonomy, system_prompt
3. It's immediately available via `hive spawn <name>`
