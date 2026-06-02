# Installation

## Requirements

- Python 3.11 or later
- At least one LLM provider (API key or local model server)

## Install from PyPI

```bash
pip install hive-agent
```

Or with [uv](https://docs.astral.sh/uv/):

```bash
uv add hive-agent
```

The default install includes the Anthropic, OpenAI, and MCP SDKs plus the CLI.
Optional extras let you pin or opt into individual pieces:

```bash
pip install 'hive-agent[anthropic]'   # Anthropic SDK
pip install 'hive-agent[openai]'      # OpenAI SDK (also Groq/Fireworks/Ollama/LM Studio)
pip install 'hive-agent[mcp]'         # MCP client/server
pip install 'hive-agent[cli]'         # Typer CLI
pip install 'hive-agent[voice]'       # audio + hotkeys (speech)
```

If a provider's SDK is missing, constructing it raises a clear
`MissingDependencyError` naming the extra to install.

## Development Install

For contributing or running from source:

```bash
git clone https://github.com/chiruu12/Hive.git && cd Hive
uv sync
```

This installs dev dependencies (pytest, ruff, mypy) automatically.

## API Keys

Create a `.env` file in your project root:

```bash
# Required -- at least one provider
ANTHROPIC_API_KEY=sk-ant-...

# Optional -- additional providers
OPENAI_API_KEY=sk-...
GROQ_API_KEY=gsk_...
FIREWORKS_API_KEY=fw_...
```

### Local Models (No API Key)

Hive auto-detects [Ollama](https://ollama.com) and [LM Studio](https://lmstudio.ai) when they're running locally. No API key needed:

```python
from hive import Agent
from hive.models.ollama import Ollama

agent = Agent(name="local", model=Ollama.standard())
```

## Verify Installation

```bash
python -c "from hive import Agent; print('Hive installed successfully')"
```

Or test the CLI:

```bash
hive --help
```
