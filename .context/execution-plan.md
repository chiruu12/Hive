# Hive Execution Plan

## What's Done

- [x] README.md (project pitch, quick start, features)
- [x] CLAUDE.md (dev conventions, architecture)
- [x] pyproject.toml (dependencies, scripts, packaging)
- [x] CLI stub (all commands defined, imports stubbed)
- [x] Agent profiles (5 presets with personalities)
- [x] Core protocols (ModelProvider, ToolExecutor, AgentProfile, AgentState)
- [x] Project structure (all modules created)
- [x] LICENSE (MIT)
- [x] Launcher scripts (start.sh, stop.sh)

---

## Phase 1: Single Agent Working (Priority: HIGH)

Goal: `hive spawn coder --task "write hello world"` actually works end-to-end.

### 1.1 Memory Store
**File:** `src/hive/memory/store.py`
- SQLite database initialization (create tables on first run)
- Tables: agents, tasks, messages, tool_results
- CRUD operations for each table
- Async via aiosqlite

### 1.2 Event Log
**File:** `src/hive/memory/events.py`
- JSONL append-only writer
- Event types: agent_spawned, task_started, step_executed, task_completed, error
- Stream reader (for `hive logs`)
- Replay function (for `hive replay`)

### 1.3 Claude Model Provider
**File:** `src/hive/models/claude.py`
- Implement ModelProvider protocol
- `complete()`: call Anthropic API with messages + tools
- `plan()`: given objective + tools, return list of PlanSteps
- Handle streaming, token counting, error handling
- Auto-detect API key from env

### 1.4 Built-in Tools (core set)
**Files:** `src/hive/execution/tools/filesystem.py`, `shell.py`, `git.py`, `memory_tools.py`
- `file_read(path)` - read file contents
- `file_write(path, content)` - write file
- `file_list(directory)` - list directory
- `shell_exec(command)` - run shell command (with allowlist)
- `git_status()`, `git_commit(message)`, `git_branch(name)`
- `memory_set(key, value)`, `memory_get(key)`

### 1.5 Tool Registry
**File:** `src/hive/execution/registry.py`
- Auto-discover tools from `execution/tools/` package
- Register by name, store ToolDefinition
- `execute(tool_name, agent_id, **params) -> ToolResult`
- `list_tools() -> list[ToolDefinition]`

### 1.6 Agent Loop
**File:** `src/hive/agents/loop.py`
- Core function: `async run_task(profile, task, store, model, tools) -> TaskResult`
- Steps:
  1. Build system prompt from profile
  2. Call model.plan(task, available_tools)
  3. For each step: execute tool, collect result
  4. Substitute {result} into next step params
  5. On failure: replan from failed step (max 2 retries)
  6. Validate output (did something actually get produced?)
  7. Log everything to event store

### 1.7 Daemon Setup
**File:** `src/hive/daemon/setup.py`
- `initialize_hive()`: create .hive/ directory, config.yaml, state.db
- Detect available models (check API keys, binaries, endpoints)
- Copy default profiles

### 1.8 Daemon Lifecycle
**File:** `src/hive/daemon/lifecycle.py`
- `spawn_agent(name, task, model_override)` - load profile, create state, start loop
- `kill_agent(name)` - mark dead, stop execution
- `get_all_agents()` - list current states

### 1.9 Wire CLI to Real Implementations
- Connect CLI commands to lifecycle/store/events
- `hive init` -> setup.initialize_hive()
- `hive spawn` -> lifecycle.spawn_agent()
- `hive status` -> lifecycle.get_all_agents()
- `hive logs` -> events.stream_agent_events()

---

## Phase 2: Multi-Model + Detection

### 2.1 LM Studio Provider
**File:** `src/hive/models/local.py`
- OpenAI-compatible API (localhost:1234)
- Detect if LM Studio is running
- List available models from endpoint

### 2.2 Codex CLI Provider
**File:** `src/hive/models/codex.py`
- Wrap `codex` CLI via subprocess
- Detect if codex binary exists
- Parse output

### 2.3 Model Router
**File:** `src/hive/models/router.py`
- `detect_models()` - scan for all available providers
- `get_model(preference, task_complexity)` - return best available
- Fallback logic: local -> sonnet -> opus
- Cost estimation per provider

### 2.4 Config System
**File:** `src/hive/daemon/config.py`
- Load `.hive/config.yaml`
- Merge with defaults
- Validate schema (pydantic)
- Support env var substitution (${ANTHROPIC_API_KEY})

---

## Phase 3: Multi-Agent + Rooms

### 3.1 Agent Messaging
**File:** `src/hive/rooms/messaging.py`
- `send_message(from_agent, to_agent, content)`
- `get_inbox(agent_id) -> list[Message]`
- Messages stored in SQLite

### 3.2 Rooms
**File:** `src/hive/rooms/room.py`
- Create room with named agents
- Post messages to room (visible to all members)
- Agent picks up messages that match its role
- Turn-based or event-driven collaboration

### 3.3 Oracle Review
**File:** `src/hive/agents/oracle.py`
- `request_review(agent_id, proposal, context) -> Approval|Rejection`
- Oracle uses Opus model
- Injected into agent loop when autonomy=medium and action is high-risk

### 3.4 Concurrent Agent Execution
- Thread pool or asyncio tasks for parallel agents
- Shared state via SQLite (serialized access)
- Event bus for real-time notifications

---

## Phase 4: Skills + Tool Synthesis

### 4.1 Skill Loader
**File:** `src/hive/skills/loader.py`
- Load SKILL.md files from `.hive/skills/` and `profiles/skills/`
- Parse YAML frontmatter for triggers
- Inject skill content into agent system prompt when relevant

### 4.2 Tool Synthesis
**File:** `src/hive/execution/synthesis.py`
- Agent calls `create_tool(name, description, code)`
- Write Python to `.hive/tools/{name}.py`
- Validate (parse AST, basic test)
- Hot-load into registry

### 4.3 MCP Server
**File:** `src/hive/mcp/server.py`
- Expose Hive as MCP tools for Claude Code
- Tools: spawn_agent, kill_agent, chat_agent, get_status, list_agents
- Users can manage Hive agents from within Claude Code sessions

---

## Phase 5: Polish + Launch

### 5.1 Demo GIF
- Record terminal session showing agents collaborating
- Keep under 15 seconds
- Show: spawn, task assignment, agent working, result

### 5.2 CONTRIBUTING.md
- How to add tools, models, agent presets
- Dev setup instructions

### 5.3 GitHub Actions
- CI: lint + type check + tests on push
- Release: publish to PyPI on tag

### 5.4 Launch
- Hacker News / Reddit post
- Tweet thread showing the demo
- Cross-post to AI/agent communities

---

## Estimated LOC per Phase

| Phase | Files | LOC | Time |
|-------|-------|-----|------|
| Phase 1 | 9 files | ~1500 | 2-3 days |
| Phase 2 | 4 files | ~600 | 1-2 days |
| Phase 3 | 4 files | ~800 | 2-3 days |
| Phase 4 | 3 files | ~500 | 1-2 days |
| Phase 5 | misc | ~200 | 1 day |
| **Total** | **~20 files** | **~3600** | **~10 days** |

---

## Key Principle

Every phase must leave the project in a working state. Phase 1 alone should be demoable. Don't build Phase 2 features into Phase 1 code "for later" - keep each phase minimal and functional.
