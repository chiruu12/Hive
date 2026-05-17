# Hive Agent Examples

## Setup

```bash
pip install hive-agent
export ANTHROPIC_API_KEY=sk-ant-...
```

## Examples

| # | File | What it demonstrates |
|---|------|---------------------|
| 1 | [01_quickstart.py](01_quickstart.py) | Minimal agent with `Instructions` — ask a question, get an answer |
| 2 | [02_tools.py](02_tools.py) | Agent with file/shell/git tools — writes and runs code |
| 3 | [03_structured_output.py](03_structured_output.py) | Pydantic `response_model` via `run_structured` and `run_once_structured` |
| 4 | [04_multi_agent.py](04_multi_agent.py) | Lead agent delegates to coder + reviewer |
| 5 | [05_mcp_tools.py](05_mcp_tools.py) | Connect to MCP servers for external tools |
| 6 | [06_cli_agent.yaml](06_cli_agent.yaml) | YAML config for `hive agent run` |
| 7 | [07_custom_toolkit.py](07_custom_toolkit.py) | Build domain-specific Toolkit + standalone `@tool` functions |
| 8 | [08_workflow_pipeline.py](08_workflow_pipeline.py) | Chain agents in a research → draft → edit pipeline |
| 9 | [09_error_handling.py](09_error_handling.py) | Status checks, budget limits, max steps, tool error recovery |
| 10 | [10_multi_provider.py](10_multi_provider.py) | Compare models, tiered routing by task complexity |
| 11 | [11_notepad_presets.py](11_notepad_presets.py) | Notepad with presets — journal, evolution, custom |
| 12 | [12_web_research.py](12_web_research.py) | Agent that searches the web and writes findings |
| 13 | [13_instructions_deep_dive.py](13_instructions_deep_dive.py) | All ways to configure agents — Instructions, Persona, response_model, toolkit auto-merge |
| 14 | [14_memory_and_comms.py](14_memory_and_comms.py) | Agents that remember things and message each other |
| 15 | [15_zero_config.py](15_zero_config.py) | Every toolkit with zero setup — just create and go |

## Running

```bash
# Run any example directly
uv run python examples/01_quickstart.py

# Interactive CLI agent from YAML config
hive agent run examples/06_cli_agent.yaml

# Quick-start interactive agent with tools
hive agent chat
```

## Progression

- **Getting Started** (01, 15): Minimal agent, zero-config toolkits
- **Tools & Output** (02, 03, 07): File/shell/git tools, structured output, custom toolkits
- **Agent Intelligence** (11, 12, 13, 14): Notepad presets, web research, instructions, memory
- **Multi-Agent** (04, 05, 08): Delegation, MCP integration, workflow pipelines
- **Production** (09, 10): Error handling, budget control, multi-provider routing
