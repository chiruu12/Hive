# Changelog

## [0.5.1] — 2026-05-31

### Fixed
- **No-tools tool-call recovery** — when a provider (e.g. Groq) rejects a tool call made on a no-tools request (`tool_use_failed`), the OpenAI-compatible adapter now retries once with a text-only instruction and falls back to clean text instead of surfacing a 400, so a multi-action turn (e.g. "make three notes") completes after its tools run. Covers both `generate_with_metadata` and `generate_stream`. Detection is provider-agnostic (by error code/message); `Agent.run_once` also nudges the final wrap-up call toward plain text.

## [0.5.0] — 2026-05-29

Composable-core and daemon-scalability release. Most changes are additive; the
public `Agent`, provider, and toolkit APIs stay backward compatible.

### Added
- **Streaming** — `BaseProvider.generate_stream()` + `StreamEvent`; native token streaming for Anthropic and OpenAI-compatible providers; `Agent(on_text=...)` streams assistant text during `run()`.
- **Provider capability model** — `Capability` enum + `supports()`, and `Availability` enum + `availability()` (distinguishes "no API key" from "unreachable"); `hive models` shows the reason for unavailable local servers.
- **Concurrent agent cycles** — the daemon runs agents' cycles concurrently with bounded concurrency (`daemon.max_concurrent_agents`, default 8); each cycle is isolated so one slow/failing agent never blocks the others.
- **Typed error hierarchy** — `HiveError` base with `AgentNotFoundError` and `ProfileNotFoundError` (each subclasses the builtin it replaced).
- **`ClipboardToolkit.read_clipboard`** — read the system clipboard (`pbpaste`/`xclip -o`), complementing the existing copy tools.
- **`HiveDaemon.start(max_cycles=...)`** — bounded daemon runs via the public API.
- **`InstructionLike` protocol** and a first-class, documented, tested standalone `Agent` path (+ example 23).

### Changed
- Tool calls within a single model turn now execute **concurrently** (`asyncio.gather`) with per-call error isolation and ordered results.
- `BaseProvider.generate_structured` is now concrete with a prompt-based fallback, so every provider supports structured output; message/tool/response conversion extracted to shared, tested `models/conversion.py`.
- Per-agent provider and profile are cached across daemon cycles (rebuilt on model/profile change).
- SQLite store gained indexes on hot columns and versioned migrations (`PRAGMA user_version`).
- `api.py` no longer reaches into daemon internals.

### Fixed
- `Toolkit.__copy__` resets the tool cache so a rebound clone's tools bind to the clone (not the original agent).

## [0.4.2] — 2026-05-28

### Added
- **TaskToolkit**: `uncomplete_task` -- reopen completed tasks, `update_task` -- modify description/priority/due date, priority filtering on `list_tasks`
- **KnowledgeToolkit**: `delete_note` -- delete notes by ID, `update_note` -- edit content/tags in-place preserving ID and timestamp
- **AlarmToolkit**: `set_alarm_at` -- absolute time alarms ("3pm", "15:00", "tomorrow 9am") via python-dateutil, local timezone support
- **SemanticMemory/TFIDFBackend**: `update()` method for in-place record editing
- New dependency: `python-dateutil>=2.8`

### Fixed
- Groq provider test leaked `OPENAI_API_KEY` from `.env` -- now patches both provider references

## [0.4.1] — 2026-05-26

### Fixed
- **Race condition** with shared toolkits -- clone-on-rebind prevents concurrent agent requests from corrupting toolkit state

## [0.4.0] — 2026-05-24

### Added
- **ClipboardToolkit** -- `copy_to_clipboard`, `copy_note`, `copy_task`, `copy_link` (pbcopy/xclip)
- **Public query methods** on TaskToolkit, AlarmToolkit, KnowledgeToolkit for host applications
- **Configurable notification title** in AlarmChecker
- **Agent auto-rebinds toolkits** bound to a different agent
- **Metadata search in TFIDF** -- tags, URLs, and metadata indexed alongside content

### Fixed
- `tc.arguments` None crash when LLM calls tools with no required params
- Integer params break Groq -- all LLM-facing numeric params changed to `str`
- WhisperLocal blocking inference -- now runs in `run_in_executor()`
- MLX whisper model map -- correct HuggingFace repo names

## [0.3.0] — 2026-05-18

### Added
- **Persona class** — inherits from Instructions, adds personality/values/fears/purpose + dynamic behavioral fields (risk_tolerance, social_drive, concentration, autonomy_level, happiness)
- **Suffering→behavior link** — suffering mechanically modifies Persona params each daemon cycle (futility → risk tolerance, invisibility → social drive, crisis → extreme params)
- **3 dramatic profiles** — gambler (risk_tolerance=0.85), philosopher (autonomy=0.9), hustler (social_drive=0.95)
- **Enhanced `hive watch` TUI** — 4-panel layout (Agents/Activity/Vitals/Drama), suffering bars, happiness emoji, risk indicators, `--compact` flag
- **`hive demo survival`** — 3 agents, 30 cycles, economy on, Rich summary
- **`hive demo detective`** — multi-model murder mystery with Rich output
- **OSS scaffolding** — CONTRIBUTING.md, CODE_OF_CONDUCT.md, issue/PR templates, release workflow

### Changed
- All 5 existing profiles now include `persona:` section with values, fears, purpose, goals
- `AgentProfile.from_yaml()` parses persona sections into `PersonaConfig`
- `Agent.__init__()` accepts `persona: Persona | None` param
- `lifecycle.spawn_agent()` uses Persona when profile has persona_config
- Checkpoint model includes `persona_snapshot` field
- Existence loop includes behavioral state in goal generation prompts

## [0.2.0] — 2026-05-14

### Added
- **Instructions class** — structured prompt configuration (persona, instructions, context)
- **Tools restructured** into `hive/tools/` with per-toolkit directories and auto-bind
- **Notepad presets** — journal, evolution, tool_requests, custom from YAML
- **Sub-agent spawning** with parent-child lifecycle (max depth 2, max 5 children)
- **A2A protocol** — 9 message types, JSONL-backed inbox/outbox, 5 collaboration patterns
- **Web browsing toolkit** — fetch + search via DuckDuckGo
- **Scheduled goals** — agents can schedule recurring goals
- **HTML run reports** — standalone export with agent cards, timelines, graphs
- **Model benchmarking** — compare models on scenarios with cost tracking
- 15 examples covering all SDK features

### Changed
- **Provider system** — `BaseProvider` ABC with `.lite()/.standard()/.pro()` tier presets
- Agent has `__repr__`/`__str__`, extracted run() helpers, budget enforcement
- All toolkits use auto-bind and zero-config defaults

## [0.1.0] — 2026-05-06

### Added
- Core agent framework with ReAct loop
- Daemon heartbeat loop driving autonomous agents
- Suffering system (6 stressor types, escalation, crisis handling)
- Existence loop for autonomous goal generation
- World economy (jobs, money, skills, gambling)
- Structured logging (full tool I/O, decisions, goals, suffering)
- 4 LLM providers (Anthropic, OpenAI, Fireworks, Ollama)
- MCP server for external control
- CLI with 20+ commands
- PyPI package: `pip install hive-agent`
