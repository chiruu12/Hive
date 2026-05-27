# Changelog

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
