# Hive Agent Examples

## Setup

```bash
pip install hive-agent
export ANTHROPIC_API_KEY=sk-ant-...
```

## Examples

| # | File | What it demonstrates |
|---|------|---------------------|
| 1 | [01_quickstart.py](01_quickstart.py) | Minimal agent — ask a question, get an answer |
| 2 | [02_tools.py](02_tools.py) | Agent with file/shell/git tools — writes and runs code |
| 3 | [03_structured_output.py](03_structured_output.py) | Pydantic models via `run_structured` and `run_once_structured` |
| 4 | [04_multi_agent.py](04_multi_agent.py) | Lead agent delegates to coder + reviewer |
| 5 | [05_mcp_tools.py](05_mcp_tools.py) | Connect to MCP servers for external tools |
| 6 | [06_cli_agent.yaml](06_cli_agent.yaml) | YAML config for `hive agent run` |
| 7 | [07_custom_toolkit.py](07_custom_toolkit.py) | Build domain-specific Toolkit + standalone `@tool` functions |
| 8 | [08_workflow_pipeline.py](08_workflow_pipeline.py) | Chain agents in a research → draft → edit pipeline |
| 9 | [09_error_handling.py](09_error_handling.py) | Status checks, budget limits, max steps, tool error recovery |
| 10 | [10_multi_provider.py](10_multi_provider.py) | Compare models, tiered routing by task complexity |

## Running

```bash
# Run any example directly
python examples/01_quickstart.py

# Interactive CLI agent from YAML config
hive agent run examples/06_cli_agent.yaml

# Quick-start interactive agent with tools
hive agent chat

# Quick-start with a specific model
hive agent chat --model claude-sonnet-4-6
```

## Progression

- **Beginner** (01, 06): Basic agent creation and YAML config
- **Intermediate** (02, 03, 07): Tools, structured output, custom toolkits
- **Advanced** (04, 05, 08): Multi-agent delegation, MCP, workflows
- **Production** (09, 10): Error handling, budget control, multi-provider routing
