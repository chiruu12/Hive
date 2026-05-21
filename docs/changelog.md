# Changelog

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
