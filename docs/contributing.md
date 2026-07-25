# Contributing to Hive

## Branching Rules

**Never push directly to `main`.** Always create a feature branch and open a PR.

```bash
git checkout -b feat/my-feature   # new feature
git checkout -b fix/bug-name      # bug fix
git checkout -b docs/update       # documentation
git checkout -b ci/improvement    # CI/CD changes
```

Open a PR to `main`, wait for CI to pass, then merge.

## Merge gate (CI)

Every PR runs the **fast gate**; pushes to `main`/`dev` also run the **full merge gate**. See [framework stabilization index](plans/framework-stabilization-index.md) for measured baselines.

### PR fast gate (required)

```bash
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
uv run mypy src/
uv run pytest tests/ -v --ignore=tests/adversarial/
uv run pytest tests/adversarial/ -v --tb=short
uv run mkdocs build --strict
```

### Merge gate (push to main / dev)

```bash
uv run pytest tests/ -v --cov=hive --cov-report=term --cov-fail-under=77
git archive HEAD | tar -x -C /tmp/hive-ci-build && cd /tmp/hive-ci-build && uv build
```

A weekly scheduled **soak** job repeats the wake-source leak test 50× and runs the full suite for ordering sensitivity.

## Development Setup

```bash
git clone https://github.com/chiruu12/Hive.git
cd Hive
uv sync
uv run pytest          # run tests
uv run ruff check src  # lint
uv run ruff format src # format
```

## Project Structure

```
src/hive/
├── runtime/       # Agent framework core (Agent, Instructions, Persona, tools)
├── agents/        # Autonomy, suffering, identity, profiles, specialization
├── daemon/        # Heartbeat loop, lifecycle management
├── models/        # LLM providers (Anthropic, OpenAI, Groq, Fireworks, Ollama, LMStudio)
├── tools/         # Toolkits (file, shell, git, web, notepad, memory, comms, A2A)
├── interactions/  # A2A protocol, collaboration patterns
├── memory/        # SQLite store, semantic memory, event log
├── world/         # Economy simulation (jobs, money, skills, events)
├── demos/         # Built-in demos (survival, detective)
├── cli/           # Typer CLI commands
└── mcp/           # MCP server for external control
```

## Adding a New Toolkit

1. Create `src/hive/tools/<name>/` with `__init__.py` and `toolkit.py`
2. Subclass `Toolkit`, decorate methods with `@tool()`
3. JSON Schema is auto-extracted from type hints
4. Add tests in `tests/runtime/` or `tests/`
5. Export from `src/hive/tools/<name>/__init__.py`

## Adding a New Provider

1. Create `src/hive/models/<name>.py`
2. Subclass `BaseProvider`, implement `generate_with_metadata()`
3. Add `.lite()`, `.standard()`, `.pro()` tier classmethods
4. Add model entries to `models.yaml`
5. Add routing in `src/hive/models/factory.py`
6. Add tests in `tests/`

## Adding a New Profile

1. Create `profiles/<name>.yaml` following existing format
2. Include `persona:` section with values, fears, purpose, goals
3. Test with `hive spawn <name>`

## Pull Request Guidelines

- One logical change per PR
- All [merge gate](#merge-gate-ci) commands must pass locally before opening a PR
- Include a clear description of what changed and why
- Reference any related issues
