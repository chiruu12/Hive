# Hive

**Local-first agent OS.** Spawn persistent AI agents that collaborate, write code, and use tools autonomously. One command to start. No Docker. No cloud dependency.

```bash
pip install hive-agents
hive init
hive spawn coder --task "write tests for the auth module"
```

Agents persist between sessions, synthesize their own tools, collaborate in shared rooms, and get reviewed by an Oracle (Opus-level model) before committing critical changes.

## Why Hive

Every agent framework makes you write orchestration code. Hive gives you a runtime. Define agents in YAML, give them tools, point them at a workspace. They figure out the rest.

| Feature | Hive | Others |
|---------|------|--------|
| Install | `pip install` | Docker, 15 config files |
| Define agents | YAML profiles | Python classes |
| Multi-model | Claude + Codex + LM Studio | Usually one provider |
| Agent collaboration | Built-in rooms + messaging | DIY orchestration |
| Persistence | Automatic (SQLite + events) | Manual state management |
| Tool creation | Agents synthesize their own | Hardcoded tool sets |
| Safety | Per-agent workspace isolation + Oracle review | Trust or nothing |

## Quick Start

```bash
# Install
pip install hive-agents

# Initialize a hive in current directory
hive init

# Spawn an agent and give it work
hive spawn coder --task "refactor the database module into async"

# Watch it work
hive logs coder

# Chat with it directly
hive chat coder

# Check all agents
hive status
```

## Pre-Built Agents

Hive ships with agent presets you can spawn immediately:

| Agent | Role | Default Model |
|-------|------|---------------|
| `coder` | Write and modify code | Sonnet |
| `reviewer` | Review code, find bugs, suggest improvements | Sonnet |
| `researcher` | Explore codebases, read docs, summarize findings | Haiku |
| `tester` | Write and run tests, report coverage gaps | Sonnet |
| `oracle` | Review proposals from other agents, approve/reject | Opus |

```bash
# Use a preset
hive spawn coder

# Or define your own in .hive/agents/
hive spawn my-custom-agent
```

## Agent Profiles (YAML)

```yaml
# .hive/agents/coder.yaml
name: coder
role: "Write, modify, and refactor code based on specifications"
model: claude-sonnet-4-6
tools:
  - file_read
  - file_write
  - shell_exec
  - git
  - ask_oracle
workspace: ./workspace/coder
autonomy: high
system_prompt: |
  You are a senior developer. Write clean, tested code.
  Follow existing patterns in the codebase.
  Commit after each logical unit of work.
```

## Multi-Model Support

Hive auto-detects available models on your system:

```bash
hive models
# Claude API: claude-sonnet-4-6, claude-haiku-4-5 (API key found)
# Codex CLI: codex (installed at /usr/local/bin/codex)
# LM Studio: llama-3.1-8b, qwen-2.5-coder (running on localhost:1234)
```

Configure per-agent or let the router decide:

```yaml
# Agent uses specific model
model: claude-sonnet-4-6

# Or let router pick based on task complexity
model: auto
routing:
  simple: local        # Fast queries go to LM Studio
  complex: sonnet      # Heavy reasoning to Claude
  review: opus         # Critical reviews to Opus
```

## Agent Rooms

Agents collaborate in named rooms:

```bash
# Create a room with multiple agents
hive room "feature-auth" --agents coder,reviewer,tester

# Post a task to the room
hive room "feature-auth" --message "implement JWT authentication"

# Agents coordinate: coder writes, reviewer checks, tester validates
# Watch the conversation
hive room "feature-auth" --follow
```

## Oracle Review

The Oracle is a high-capability model (Opus) that reviews agent work before critical actions:

```bash
# Agents with autonomy: medium automatically request Oracle review
# before commits, file deletions, or cross-agent operations

# You can also be the oracle yourself
hive oracle --manual  # You approve/reject agent proposals
```

## Tool Synthesis

Agents can create new tools when they need capabilities that don't exist:

```bash
# Agent encounters a task requiring a tool that doesn't exist
# It writes the tool, tests it, and registers it for future use

hive tools list          # See all available tools (built-in + synthesized)
hive tools history       # See what tools agents have created
```

## Skills Integration

Hive agents can load skills (structured workflows) for complex tasks:

```bash
# Built-in skills
hive skills list

# Agents automatically load relevant skills based on task context
# Example: coder agent loads TDD skill when writing tests
```

## CLI Reference

```bash
hive init                          # Initialize hive in current directory
hive spawn <agent> [--task <msg>]  # Spawn an agent (optionally with initial task)
hive kill <agent>                  # Terminate an agent
hive status                        # Show all agents and their current state
hive chat <agent>                  # Interactive chat with an agent
hive logs <agent>                  # Stream agent activity
hive room <name> [--agents a,b]   # Create or join a room
hive models                        # Show available models
hive tools list                    # Show available tools
hive skills list                   # Show available skills
hive replay <session-id>           # Replay a past session
hive config                        # Edit hive configuration
```

## Configuration

```yaml
# .hive/config.yaml
models:
  claude:
    api_key: ${ANTHROPIC_API_KEY}
    default: claude-sonnet-4-6
  codex:
    path: /usr/local/bin/codex
  local:
    endpoint: http://localhost:1234/v1
    default: qwen-2.5-coder-7b

defaults:
  autonomy: medium
  max_steps: 20
  workspace_isolation: true

oracle:
  model: claude-opus-4-6
  auto_review: true
  review_threshold: high  # low/medium/high risk actions trigger review
```

## Architecture

```
.hive/
├── config.yaml          # Global configuration
├── agents/              # Agent profiles (YAML)
│   ├── coder.yaml
│   ├── reviewer.yaml
│   └── custom.yaml
├── skills/              # Loaded skills (markdown workflows)
├── tools/               # Synthesized tools (Python)
├── state.db             # SQLite (agents, tasks, messages)
├── events.jsonl         # Immutable event log
└── workspaces/          # Per-agent isolated directories
    ├── coder/
    └── reviewer/
```

## Requirements

- Python 3.11+
- At least one model provider:
  - Claude API key (`ANTHROPIC_API_KEY`) OR
  - Codex CLI installed OR
  - LM Studio / Ollama running locally

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT
