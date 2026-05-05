# Hive Development

## Project Overview

Hive is a local-first agent operating system. Users spawn persistent AI agents via CLI that collaborate, write code, and use tools autonomously. Config-driven with YAML agent profiles, multi-model support (Claude, Codex, LM Studio), and built-in safety via workspace isolation and Oracle review.

## Architecture

```
src/hive/
├── cli/              # Typer CLI (commands map 1:1 to user actions)
├── daemon/           # Background service (lifecycle, scheduler, events)
├── agents/           # Agent runtime (loop, profile loading, state)
├── execution/        # Tool execution (sandbox, registry, synthesis)
├── memory/           # Persistence (SQLite store, JSONL events)
├── models/           # LLM abstraction (router, claude, codex, local)
├── rooms/            # Multi-agent collaboration (rooms, messaging)
└── skills/           # Skill loader (markdown workflow parser)
```

## Tech Stack

- **Language**: Python 3.11+
- **CLI**: Typer + Rich (terminal UI)
- **Async**: asyncio (concurrent agent execution)
- **Database**: SQLite via aiosqlite
- **LLM**: anthropic SDK, OpenAI-compatible API, subprocess for Codex
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
- Tests mirror src structure: `tests/agents/test_loop.py` tests `src/hive/agents/loop.py`

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

- Custom exception hierarchy rooted at `HiveError`
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
2. **Results flow between steps via substitution.** Plan = list of steps. Each step's output substitutes into the next step's params.
3. **Tools are just functions.** The execution engine is a dispatcher: resolve tool_id -> call function -> return result.
4. **YAML profiles define agents.** Role, model, tools, autonomy level, system prompt. No code needed to create an agent.
5. **Event log is immutable.** JSONL append-only. Enables replay, debugging, and recovery.
6. **Model router is pluggable.** Protocol-based. Add new providers without changing agent code.
7. **Skills are markdown.** Parsed at runtime, loaded into agent context when relevant.

## Commands

```bash
# Development
uv run pytest                    # Run tests
uv run pytest tests/agents/      # Run specific test module
uv run python -m hive.cli        # Run CLI locally
uv run ruff check src/           # Lint
uv run ruff format src/          # Format
uv run mypy src/                 # Type check

# All checks
uv run pytest && uv run ruff check src/ && uv run mypy src/
```

## Adding a New Tool

1. Create function in `src/hive/execution/tools/`
2. Decorate with `@tool(name="tool_name", description="...")`
3. Tool is auto-registered on startup
4. Add to relevant agent profiles in `profiles/`

## Adding a New Model Provider

1. Implement `ModelProvider` protocol in `src/hive/models/`
2. Register in `src/hive/models/router.py`
3. Add detection logic (API key? binary exists? endpoint responding?)
4. Add to config schema

## Adding a New Agent Preset

1. Create YAML file in `profiles/`
2. Define: name, role, model, tools, autonomy, system_prompt
3. It's immediately available via `hive spawn <name>`
