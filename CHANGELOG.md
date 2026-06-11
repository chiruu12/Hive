# Changelog

## [Unreleased]

### Fixed
- **Daemon shutdown is now guaranteed** — `HiveDaemon.start()` runs its
  shutdown path (alarm-task teardown, shutdown checkpoints, life summaries)
  even when the heartbeat loop raises or the daemon task is cancelled, and
  `hive serve --with-daemon` now awaits the daemon's shutdown during server
  teardown instead of abandoning the cancelled task. Previously a crash or
  server exit could skip checkpointing entirely and orphan the alarm task.
- **Cycle errors can no longer cascade** — if the store fails while the daemon
  is recording an agent's timeout or error (e.g. a locked database), the
  failure is logged and contained instead of escaping into `asyncio.gather`
  and killing the heartbeat for every agent.
- **Checkpoint failures are visible** — a failed world snapshot during
  checkpointing now logs a warning instead of passing silently, and corrupt
  checkpoint files are quarantined as `<name>.json.corrupt` (preserved for
  diagnosis, skipped on later listings) instead of being silently re-parsed
  and dropped on every listing.
- **Profile cache catches same-second edits** — daemon profile-cache
  invalidation now keys on `(mtime_ns, size)` instead of whole-second mtime.

## [0.6.1] — 2026-06-03

### Added
- **Deterministic mode for reproducible runs** — a `seed` config option (and
  `HIVE_SEED` env var) seeds the stochastic world layer (life-event rolls, luck,
  gambling) via per-subsystem `random.Random` streams injected into `EventEngine`
  and `WorldState`. Every run now also writes a `manifest.json`
  (`logs/runs/<run-id>/`) capturing the hive version, seed, model config, and
  spawned agents, so an experiment's setup is fully recorded. The seed governs the
  world RNG, not LLM outputs.
- **First-class named-link store** — a stable, exact, enumerable `name -> URL`
  map alongside the existing search-based link tools. New `NamedLinkStore`
  library class (JSON-backed, atomic writes, corrupt-file recovery, name
  normalization) and four `LinkToolkit` tools (`save_named_link`,
  `get_named_link`, `list_named_links`, `remove_named_link`). A host can point
  the store at its own path (`LinkToolkit(..., named_links_path=...)`) and
  read/write it directly via the library API, so an agent and a host UI share one
  source of truth. `NamedLinkStore`, `NamedLink`, and `normalize_name` are
  exported from the package; `SemanticMemory.storage_dir` exposes the agent's
  memory directory for co-locating per-agent files.

## [0.6.0] — 2026-06-02

Framework-hardening release: the agent runtime is more robust under streaming
interruptions, hung tools, and corrupt state, and the package is friendlier to
import and embed. All changes are backward compatible; existing databases
upgrade automatically.

### Added
- **Per-tool execution timeout** — `Agent(tool_timeout=...)` and the new
  `daemon.tool_timeout` config (default 60s, env-validated `>= 0`) wrap each tool
  call in a timeout. A hung tool becomes a tool-error result fed back to the
  model instead of stalling the whole cycle. `0` disables it.
- **Install extras** — `hive-agent[anthropic]`, `[openai]`, `[mcp]`, and `[cli]`.
  The SDKs still ship in the core dependencies (existing installs are unchanged),
  but the extras pave the way for a slimmer core and back the new error below.
- **Context managers + lazy init on the `Hive` facade** — `with Hive() as h:` and
  `async with Hive() as h:` both work, and `Hive(path).spawn(...)` now scaffolds
  `.hive/` lazily, so a manual `init()` call is optional. `ensure_hive_dirs()`
  is exported for embedders who want loop-safe directory scaffolding.
- **`StructuredParseError`** and **`MissingDependencyError`** typed exceptions,
  exported from the package.

### Changed
- **Streaming falls back instead of failing** — when a stream ends without a
  terminal DONE event (or errors mid-stream), the agent keeps the text already
  shown or falls back to a retried non-streaming call, rather than raising. The
  stream is closed on cancellation so the underlying connection is released.
- **`StructuredTaskResult.parsed` is now `T | None`** — a failed structured run
  returns `parsed=None` instead of an unvalidated `model_construct()` object.
- **Provider error detection is structured-first** — `response_format`/
  `json_schema` unsupported errors are matched via error code/body before any
  message-substring fallback.

### Fixed
- **Previously-silent failures are surfaced** — memory-recall failures, corrupt
  suffering/persona checkpoint restores, and plugin-init failures now log at
  warning level with context, and corrupt suffering snapshots fall back to a
  fresh state instead of being left unset.
- **Robust structured-output parsing** — a brace-matching scanner that respects
  string literals replaces the naive first-`{`/last-`}` slice, so embedded or
  nested braces no longer corrupt extraction.
- **One active generated goal per agent** — the existence loop re-checks for an
  active goal immediately before saving, so a concurrently-arriving goal
  (delegation, schedule) isn't duplicated. (Subgoals/delegation still create
  multiple active goals by design.)
- **Malformed tool-call arguments are logged** instead of silently dropped.
- **Budget enforcement** — the `run_once` wrap-up generation is now budget-checked;
  a hard budget can still overshoot by at most one generation (documented).

## [0.5.4] — 2026-06-01

Durability, simulation, and hardening release. All changes are additive and
backward compatible; existing databases and identities upgrade automatically.

### Added
- **Derived mood model** — a `CircumplexMood` maps an agent's `happiness` and
  `suffering` onto a valence/arousal circumplex and names the mood (content,
  motivated, steady, restless, discouraged, anxious, overwhelmed). Pure/derived
  (no persisted state), swappable via `MoodRegistry`, and surfaced in the
  goal-pursuit prompt.
- **Chaptered narrative** — instead of FIFO-dropping its oldest lines, an
  agent's narrative seals into compact `Chapter` summaries (date span + entry
  count + goal theme) on overflow, and the preamble shows a "Story so far"
  section. `AgentIdentity.full_narrative()` exposes the complete history.
- **Identity narrative in the runtime prompt** — the agent *pursuing* a goal
  now sees its persistent self (name + accumulated narrative), not just the
  goal-generation path.
- **Event-log fsync durability (C5)** — `EventLog(fsync=True)` flushes and
  `os.fsync()`s every append so a power/OS crash cannot lose an acknowledged
  event. Gated by the new `event_log_fsync` config option (env
  `HIVE_EVENT_LOG_FSYNC`), default off to protect the hot heartbeat write path;
  the daemon honors it. Reads now tolerate a torn/partial last line.
- **`HiveStore.delete_agent()`** — deletes an agent and, via the new cascade,
  all of its child rows in one call.
- **Test coverage (F1)** — first tests for the CLI, the MCP server protocol,
  and the structured logging writer/reader.

### Fixed
- **Event log no longer shreds records with Unicode line separators** —
  `replay()`/`stream()` split on `\n` only (not `str.splitlines()`, which also
  breaks on `\r`/`\f`/NEL/`U+2028`/`U+2029` — all legal unescaped in JSON), so
  an event whose text carried one is no longer mis-parsed as corruption.
- **Nudge delivery race** — `get_pending_nudges` marks only the nudges it
  actually read as delivered, so one inserted concurrently isn't lost.
- Dropped dead `HIVE_MAX_TURNS`/`HIVE_SESSION_TIMEOUT` env mappings (no backing
  fields); checkpoints now snapshot the freshly-saved identity; the crisis
  directive is no longer duplicated in the pursuit prompt; event-log fsync also
  fsyncs the parent directory on file creation.

### Changed
- **FK cascades (C3)** — every child table's foreign key to `agents`
  (`sessions`, `goals`, `nudges`, `schedules`, `sub_agents`, `tasks`, `alarms`)
  now declares `ON DELETE CASCADE`. A `user_version` 1→2 migration rebuilds
  existing tables to add it (data preserved). Foreign-key enforcement is opt-in
  per operation (on for `delete_agent`), so writing child rows for
  not-yet-persisted agents keeps working.
- **WAL journaling (C4)** — the store now runs in WAL mode (set persistently on
  initialize) with an explicit 5s busy timeout, so readers and a writer no
  longer lock each other out across the daemon's concurrent cycles and other
  processes (MCP server, CLI). Verified with concurrent writers and no
  "database is locked" errors (40 in the test suite; 1200 in the local stress
  harness).
- **Dependency upper bounds (E3)** — fast-moving deps are capped below their
  next major (`anthropic<1`, `httpx<1`, `openai<3`, `mcp<2`, `pydantic<3`) so a
  breaking release can't silently enter; minimums stay loose.

## [0.5.3] — 2026-06-01

### Fixed
- **SemanticMemory reflects cross-process writes** — the TF-IDF note store (behind `KnowledgeToolkit`) loaded `memories.jsonl` into an in-memory index at construction, so a note appended by another process (e.g. a host's MCP server calling `save_note` while a long-running backend held the toolkit) was invisible until restart. Reads (`search`, `recent`/`recent_sync`, `count`, `recall`) now do one cheap `stat()` and reload the index only when the file's `(mtime, size)` changed; in-process writes refresh the cached stat so they never trigger a redundant reload. The mutators (`store`, `delete`, `update`, `consolidate`) also reload first, so a note appended by another process is never masked or dropped when they write/re-save the file. Loading tolerates a partial last line from a concurrent appender. Same-process behavior is unchanged.

### CI
- Release workflow's PyPI existence check uses `curl --retry` and logs the "proceeding with publish" path explicitly (a transient network error no longer looks like a clean 404); `uv publish --check-url` remains the final guard.

## [0.5.2] — 2026-05-31

### Fixed
- **Hardened no-tools recovery** (review follow-up to 0.5.1) — streaming recovery now fires only when the `tool_use_failed` occurs *before* any text reaches the caller (no duplicated output), and a recovery stream that errors after emitting text preserves that text in its terminal result. A `tool_use_failed` on a request that *did* offer tools is no longer swallowed. The agent-layer wrap-up nudge and the adapter's text-only recovery nudge are now `user`-role messages (some strict providers reject mid-thread `system` messages); the agent nudge is sent only for the wrap-up call and isn't written to the logged conversation.

### Added
- **Phase 3 simulation core** — registry-driven world catalogs (events & jobs) and wired simulation feedback loops.

### CI
- Release workflow skips publishing when the version already exists on PyPI, so moving or re-pushing a tag can't trigger a conflicting re-upload.

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
