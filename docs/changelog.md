# Changelog

## [0.6.0] -- 2026-06-02

Framework-hardening release: the agent runtime is more robust under streaming interruptions, hung tools, and corrupt state, and the package is friendlier to import and embed. All changes are backward compatible; existing databases upgrade automatically.

### Added
- **Per-tool execution timeout**: `Agent(tool_timeout=...)` and the `daemon.tool_timeout` config (default 60s, validated `>= 0`) wrap each tool call; a hung tool becomes a tool-error fed back to the model instead of stalling the cycle. `0` disables it.
- **Install extras**: `hive-agent[anthropic]`, `[openai]`, `[mcp]`, `[cli]`. The SDKs still ship in core deps (existing installs unchanged); a missing one now raises a clear `MissingDependencyError` pointing at the extra.
- **Context managers + lazy init on `Hive`**: `with Hive() as h:` and `async with Hive() as h:` both work, and `Hive(path).spawn(...)` scaffolds `.hive/` lazily, so `init()` is optional. `ensure_hive_dirs()` is exported for loop-safe scaffolding.
- **`StructuredParseError`** and **`MissingDependencyError`** typed exceptions, exported from the package.

### Changed
- **Streaming falls back instead of failing**: a stream that ends without a terminal DONE event (or errors mid-stream) keeps the text already shown or falls back to a retried non-streaming call; the stream is closed on cancellation.
- **`StructuredTaskResult.parsed` is now `T | None`**: a failed structured run returns `parsed=None` instead of an unvalidated `model_construct()` object.
- **Provider error detection is structured-first** for unsupported `response_format`/`json_schema`.

### Fixed
- **Previously-silent failures surfaced**: memory-recall, corrupt suffering/persona restore, and plugin-init failures log at warning level; corrupt suffering snapshots fall back to a fresh state.
- **Robust structured-output parsing**: a brace-matching scanner replaces the naive first-`{`/last-`}` slice.
- **One active generated goal per agent**: the existence loop re-checks before saving (subgoals/delegation still create multiple by design).
- **Malformed tool-call arguments are logged** instead of silently dropped.

## [0.5.4] -- 2026-06-01

Durability, simulation, and hardening release. All changes are additive and backward compatible; existing databases and identities upgrade automatically.

### Added
- **Derived mood model**: a `CircumplexMood` maps `happiness` + `suffering` onto a valence/arousal circumplex and names the mood (content/motivated/steady/restless/discouraged/anxious/overwhelmed). Pure/derived, swappable via `MoodRegistry`, surfaced in the goal-pursuit prompt.
- **Chaptered narrative**: the narrative seals into compact `Chapter` summaries (date span + entry count + goal theme) on overflow instead of FIFO-dropping; the preamble shows a "Story so far" section; `AgentIdentity.full_narrative()` exposes the full history.
- **Identity narrative in the runtime prompt**: the goal-*pursuing* agent now sees its persistent self (name + accumulated narrative), not just goal generation.
- **Event-log fsync durability (C5)**: `EventLog(fsync=True)` flushes and `os.fsync()`s every append so a power/OS crash can't lose an acknowledged event. Gated by the `event_log_fsync` config option (env `HIVE_EVENT_LOG_FSYNC`), default off to protect the hot heartbeat write path; the daemon honors it. Reads tolerate a torn/partial last line.
- **`HiveStore.delete_agent()`**: deletes an agent and, via cascade, all of its child rows in one call.
- **Test coverage (F1)**: first tests for the CLI, the MCP server protocol, and the structured logging writer/reader.

### Fixed
- **Event log no longer shreds records with Unicode line separators**: `replay()`/`stream()` split on `\n` only (not `str.splitlines()`, which also breaks on `\r`/`\f`/NEL/`U+2028`/`U+2029`, all legal unescaped in JSON).
- **Nudge delivery race**: `get_pending_nudges` marks only the nudges it actually read as delivered, so one inserted concurrently isn't lost.
- Dropped dead `HIVE_MAX_TURNS`/`HIVE_SESSION_TIMEOUT` env mappings; checkpoints snapshot the freshly-saved identity; the crisis directive isn't duplicated in the pursuit prompt; event-log fsync also fsyncs the parent directory on file creation.

### Changed
- **FK cascades (C3)**: every child table's foreign key to `agents` (`sessions`, `goals`, `nudges`, `schedules`, `sub_agents`, `tasks`, `alarms`) now declares `ON DELETE CASCADE`; a `user_version` 1->2 migration rebuilds existing tables to add it (data preserved). FK enforcement is opt-in per operation, so writing child rows for not-yet-persisted agents keeps working.
- **WAL journaling (C4)**: the store runs in WAL mode (persistent) with a 5s busy timeout, so readers and a writer don't lock each other out across concurrent cycles and other processes. Verified with concurrent writers and no "database is locked" errors (40 in the test suite; 1200 in the local stress harness).
- **Dependency upper bounds (E3)**: fast-moving deps capped below their next major (`anthropic<1`, `httpx<1`, `openai<3`, `mcp<2`, `pydantic<3`); minimums stay loose.

## [0.5.3] -- 2026-06-01

### Fixed
- **SemanticMemory reflects cross-process writes**: the TF-IDF note store (behind `KnowledgeToolkit`) cached `memories.jsonl` in memory at construction, so a note appended by another process stayed invisible until restart. Reads now stat the file and reload only when `(mtime, size)` changed; in-process writes refresh the cached stat; the mutators (`store`/`delete`/`update`/`consolidate`) reload before writing so external appends aren't masked or dropped; loading tolerates a partial last line. Same-process behavior unchanged.

### CI
- Release workflow's PyPI existence check uses `curl --retry` and logs the proceed-to-publish path explicitly; `uv publish --check-url` remains the final guard.

## [0.5.2] -- 2026-05-31

### Fixed
- **Hardened no-tools recovery** (review follow-up to 0.5.1): streaming recovery now fires only when the `tool_use_failed` occurs *before* any text reaches the caller (no duplicated output), and a recovery stream that errors after emitting text preserves that text in its terminal result. A `tool_use_failed` on a request that *did* offer tools is no longer swallowed. The agent-layer wrap-up nudge and the adapter's text-only recovery nudge are now `user`-role messages (some strict providers reject mid-thread `system` messages); the agent nudge is sent only for the wrap-up call and isn't written to the logged conversation.

### Added
- **Phase 3 simulation core**: registry-driven world catalogs (events & jobs) and wired simulation feedback loops.

### CI
- Release workflow skips publishing when the version already exists on PyPI, so moving or re-pushing a tag can't trigger a conflicting re-upload.

## [0.5.1] -- 2026-05-31

### Fixed
- **No-tools tool-call recovery**: when a provider (e.g. Groq) rejects a tool call made on a no-tools request (`tool_use_failed`), the OpenAI-compatible adapter now retries once with a text-only instruction and falls back to clean text instead of surfacing a 400 -- so a multi-action turn (e.g. "make three notes") completes after its tools run. Covers both `generate_with_metadata` and `generate_stream`. Detection is provider-agnostic (by error code/message); `Agent.run_once` also nudges the final wrap-up call toward plain text.

## [0.5.0] -- 2026-05-29

Composable-core and daemon-scalability release. Most changes are additive; the public `Agent`, provider, and toolkit APIs stay backward compatible.

### Added
- **Streaming**: `BaseProvider.generate_stream()` + `StreamEvent`; native token streaming for Anthropic and OpenAI-compatible providers; `Agent(on_text=...)` streams assistant text during `run()`
- **Provider capabilities**: `Capability` + `supports()`, and `Availability` + `availability()` (distinguishes "no API key" from "unreachable"); `hive models` shows the reason for unavailable local servers
- **Concurrent agent cycles**: the daemon runs cycles concurrently with bounded concurrency (`daemon.max_concurrent_agents`, default 8), each isolated so one slow/failing agent never blocks the others
- **Typed errors**: `HiveError`, `AgentNotFoundError`, `ProfileNotFoundError` (each subclasses the builtin it replaced)
- **ClipboardToolkit**: `read_clipboard` -- read the system clipboard (`pbpaste`/`xclip -o`)
- **`HiveDaemon.start(max_cycles=...)`** for bounded runs; `InstructionLike` protocol; first-class standalone `Agent` (example 23)

### Changed
- Multiple tool calls in one model turn execute concurrently with per-call error isolation and ordered results
- `BaseProvider.generate_structured` is now concrete with a prompt-based fallback; message conversion extracted to shared `models/conversion.py`
- Per-agent provider/profile cached across daemon cycles; SQLite gained hot-column indexes and versioned migrations (`PRAGMA user_version`); `api.py` decoupled from daemon internals

### Fixed
- `Toolkit.__copy__` resets the tool cache so a rebound clone binds to itself

## [0.4.2] -- 2026-05-28

### Added
- **TaskToolkit**: `uncomplete_task` -- reopen completed tasks, `update_task` -- modify description/priority/due date, priority filtering on `list_tasks`
- **KnowledgeToolkit**: `delete_note` -- delete notes by ID, `update_note` -- edit content/tags in-place preserving ID and timestamp
- **AlarmToolkit**: `set_alarm_at` -- absolute time alarms ("3pm", "15:00", "tomorrow 9am") via python-dateutil, local timezone support
- **SemanticMemory/TFIDFBackend**: `update()` method for in-place record editing
- New dependency: `python-dateutil>=2.8`

### Fixed
- Groq provider test leaked `OPENAI_API_KEY` from `.env` -- now patches both provider references

## [0.4.1] -- 2026-05-26

### Fixed
- **Race condition** with shared toolkits -- clone-on-rebind prevents concurrent agent requests from corrupting toolkit state

## [0.4.0] -- 2026-05-24

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

## [0.3.0] -- 2026-05-18

### Added
- **Persona class** -- inherits from Instructions, adds personality/values/fears/purpose + dynamic behavioral fields (risk_tolerance, social_drive, concentration, autonomy_level, happiness)
- **Suffering→behavior link** -- suffering mechanically modifies Persona params each daemon cycle (futility → risk tolerance, invisibility → social drive, crisis → extreme params)
- **3 dramatic profiles** -- gambler (risk_tolerance=0.85), philosopher (autonomy=0.9), hustler (social_drive=0.95)
- **Enhanced `hive watch` TUI** -- 4-panel layout (Agents/Activity/Vitals/Drama), suffering bars, happiness emoji, risk indicators, `--compact` flag
- **`hive demo survival`** -- 3 agents, 30 cycles, economy on, Rich summary
- **`hive demo detective`** -- multi-model murder mystery with Rich output
- **OSS scaffolding** -- CONTRIBUTING.md, CODE_OF_CONDUCT.md, issue/PR templates, release workflow

### Changed
- All 5 existing profiles now include `persona:` section with values, fears, purpose, goals
- `AgentProfile.from_yaml()` parses persona sections into `PersonaConfig`
- `Agent.__init__()` accepts `persona: Persona | None` param
- `lifecycle.spawn_agent()` uses Persona when profile has persona_config
- Checkpoint model includes `persona_snapshot` field
- Existence loop includes behavioral state in goal generation prompts

## [0.2.0] -- 2026-05-14

### Added
- **Instructions class** -- structured prompt configuration (persona, instructions, context)
- **Tools restructured** into `hive/tools/` with per-toolkit directories and auto-bind
- **Notepad presets** -- journal, evolution, tool_requests, custom from YAML
- **Sub-agent spawning** with parent-child lifecycle (max depth 2, max 5 children)
- **A2A protocol** -- 9 message types, JSONL-backed inbox/outbox, 5 collaboration patterns
- **Web browsing toolkit** -- fetch + search via DuckDuckGo
- **Scheduled goals** -- agents can schedule recurring goals
- **HTML run reports** -- standalone export with agent cards, timelines, graphs
- **Model benchmarking** -- compare models on scenarios with cost tracking
- 15 examples covering all SDK features

### Changed
- **Provider system** -- `BaseProvider` ABC with `.lite()/.standard()/.pro()` tier presets
- Agent has `__repr__`/`__str__`, extracted run() helpers, budget enforcement
- All toolkits use auto-bind and zero-config defaults

## [0.1.0] -- 2026-05-06

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
