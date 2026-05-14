"""Serve — interactive REPL for running an agent as a CLI assistant."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from hive.runtime.agent import Agent
from hive.runtime.dev_tools import FileToolkit, GitToolkit, ShellToolkit
from hive.runtime.providers import create_runtime_provider
from hive.runtime.tools import Toolkit
from hive.runtime.types import Task, TaskStatus

logger = logging.getLogger(__name__)


class AgentServer:
    """Wraps an Agent in an interactive REPL with Rich output."""

    def __init__(
        self,
        agent: Agent,
        name: str = "",
        console: Console | None = None,
    ):
        self._agent = agent
        self._name = name or agent.name
        self._console = console or Console()
        self._history: list[str] = []

    def run(self) -> None:
        """Start the interactive REPL. Blocks until user exits."""
        asyncio.run(self._repl())

    async def _repl(self) -> None:
        c = self._console
        c.print(
            Panel(
                f"[bold]{self._name}[/bold] is ready.\n"
                f"Type a task or question. Use [cyan]/quit[/cyan] to exit.\n"
                f"Use [cyan]/tools[/cyan] to list available tools.",
                border_style="green",
            )
        )

        while True:
            try:
                user_input = c.input("[bold cyan]> [/bold cyan]").strip()
            except (EOFError, KeyboardInterrupt):
                c.print("\n[dim]Goodbye.[/dim]")
                break

            if not user_input:
                continue
            if user_input in ("/quit", "/exit", "/q"):
                c.print("[dim]Goodbye.[/dim]")
                break
            if user_input == "/tools":
                tools = self._agent.get_tools()
                if tools:
                    for t in tools:
                        c.print(f"  [cyan]{t.name}[/cyan] — {t.description}")
                else:
                    c.print("  [dim]No tools available.[/dim]")
                continue
            if user_input == "/history":
                if self._history:
                    for i, h in enumerate(self._history[-10:], 1):
                        c.print(f"  {i}. {h[:80]}")
                else:
                    c.print("  [dim]No history yet.[/dim]")
                continue

            self._history.append(user_input)

            with c.status("[bold yellow]Thinking...[/bold yellow]"):
                result = await self._agent.run(
                    Task(instruction=user_input)
                )

            if result.status == TaskStatus.COMPLETED:
                c.print()
                c.print(Markdown(result.output))
                c.print()
                if result.tool_calls_made > 0:
                    c.print(
                        f"[dim]({result.steps_taken} steps, "
                        f"{result.tool_calls_made} tool calls, "
                        f"{result.duration_seconds:.1f}s)[/dim]"
                    )
            elif result.status == TaskStatus.FAILED:
                c.print(f"\n[red]Error: {result.error}[/red]\n")
            else:
                c.print(f"\n[yellow]{result.output}[/yellow]\n")


def create_agent_from_config(config: dict[str, Any]) -> Agent:
    """Create an Agent from a configuration dict."""
    model_name = config.get("model", "claude-haiku-4-5")
    provider = create_runtime_provider(model_name)

    workspace = Path(config.get("workspace", ".")).resolve()
    toolkits: list[Toolkit] = []

    tool_names = config.get("tools", [])
    if any(t in tool_names for t in ("file_read", "file_write", "file_edit", "list_dir")):
        toolkits.append(FileToolkit(workspace))
    if "shell_exec" in tool_names:
        toolkits.append(ShellToolkit(workspace))
    if any(t in tool_names for t in ("git_status", "git_diff", "git_add", "git_commit", "git")):
        toolkits.append(GitToolkit(workspace))

    return Agent(
        name=config.get("name", "agent"),
        model=provider,
        system_prompt=config.get("system_prompt", ""),
        toolkits=toolkits,
        max_steps=config.get("max_steps", 25),
        temperature=config.get("temperature", 0.0),
        max_cost_usd=config.get("max_cost_usd", 0.0),
        max_tokens=config.get("max_tokens", 0),
    )


def serve_from_yaml(path: Path) -> None:
    """Load an agent config from YAML and start the REPL."""
    import yaml

    with open(path) as f:
        config = yaml.safe_load(f)

    agent = create_agent_from_config(config)
    server = AgentServer(agent, name=config.get("name", path.stem))
    server.run()


def serve_quick(
    model: str = "claude-haiku-4-5",
    tools: bool = True,
    workspace: str = ".",
) -> None:
    """Quick-start an agent with sensible defaults."""
    provider = create_runtime_provider(model)
    ws = Path(workspace).resolve()

    toolkits: list[Toolkit] = []
    if tools:
        toolkits = [
            FileToolkit(ws),
            ShellToolkit(ws),
            GitToolkit(ws),
        ]

    agent = Agent(
        name="assistant",
        model=provider,
        system_prompt=(
            "You are a helpful coding assistant. "
            "Use the available tools to help with tasks. "
            "Be concise and precise."
        ),
        toolkits=toolkits,
        max_steps=25,
    )

    server = AgentServer(agent, name="Hive Assistant")
    server.run()
