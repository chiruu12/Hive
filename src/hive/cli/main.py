"""Hive CLI - entry point for all user commands."""

import typer
from rich.console import Console

app = typer.Typer(
    name="hive",
    help="Local-first agent OS. Spawn persistent AI agents that collaborate and code autonomously.",
    no_args_is_help=True,
)
console = Console()


@app.command()
def init() -> None:
    """Initialize a new hive in the current directory."""
    from hive.daemon.setup import initialize_hive

    initialize_hive()
    console.print("[green]Hive initialized.[/green] Run `hive spawn coder` to create your first agent.")


@app.command()
def spawn(
    agent: str = typer.Argument(help="Agent name or preset (coder, reviewer, researcher, tester)"),
    task: str | None = typer.Option(None, "--task", "-t", help="Initial task to assign"),
    model: str | None = typer.Option(None, "--model", "-m", help="Override default model"),
) -> None:
    """Spawn a new agent (from preset or custom profile)."""
    from hive.daemon.lifecycle import spawn_agent

    result = spawn_agent(agent, task=task, model_override=model)
    console.print(f"[green]Spawned[/green] {result.name} ({result.model})")
    if task:
        console.print(f"  Task: {task}")


@app.command()
def status() -> None:
    """Show all running agents and their current state."""
    from hive.daemon.lifecycle import get_all_agents

    agents = get_all_agents()
    if not agents:
        console.print("[dim]No agents running. Use `hive spawn` to create one.[/dim]")
        return

    from rich.table import Table

    table = Table(title="Hive Agents")
    table.add_column("Agent", style="cyan")
    table.add_column("Role", style="dim")
    table.add_column("Model", style="green")
    table.add_column("Status")
    table.add_column("Current Task", style="dim")

    for a in agents:
        table.add_row(a.name, a.role, a.model, a.status, a.current_task or "-")

    console.print(table)


@app.command()
def chat(agent: str = typer.Argument(help="Agent to chat with")) -> None:
    """Open interactive chat with an agent."""
    from hive.rooms.chat import interactive_chat

    interactive_chat(agent)


@app.command()
def kill(agent: str = typer.Argument(help="Agent to terminate")) -> None:
    """Terminate a running agent."""
    from hive.daemon.lifecycle import kill_agent

    kill_agent(agent)
    console.print(f"[red]Killed[/red] {agent}")


@app.command()
def logs(agent: str = typer.Argument(help="Agent to stream logs for")) -> None:
    """Stream an agent's activity log in real-time."""
    from hive.memory.events import stream_agent_events

    stream_agent_events(agent)


@app.command()
def room(
    name: str = typer.Argument(help="Room name"),
    agents: str | None = typer.Option(None, "--agents", "-a", help="Comma-separated agent names"),
    message: str | None = typer.Option(None, "--message", "-m", help="Post a message to the room"),
    follow: bool = typer.Option(False, "--follow", "-f", help="Follow room messages"),
) -> None:
    """Create, join, or interact with an agent room."""
    from hive.rooms.room import manage_room

    manage_room(name, agents=agents, message=message, follow=follow)


@app.command()
def models() -> None:
    """Show available models and their status."""
    from hive.models.router import detect_models

    available = detect_models()
    for provider, model_list in available.items():
        console.print(f"\n[bold]{provider}[/bold]:")
        for m in model_list:
            status = "[green]available[/green]" if m.available else "[red]unavailable[/red]"
            console.print(f"  {m.name}: {status}")


@app.command()
def tools() -> None:
    """List all available tools (built-in + synthesized)."""
    from hive.execution.registry import list_tools

    all_tools = list_tools()
    from rich.table import Table

    table = Table(title="Available Tools")
    table.add_column("Tool", style="cyan")
    table.add_column("Type", style="dim")
    table.add_column("Description")

    for t in all_tools:
        table.add_row(t.name, t.tool_type, t.description)

    console.print(table)


@app.command()
def skills() -> None:
    """List available skills that agents can load."""
    from hive.skills.loader import list_skills

    all_skills = list_skills()
    for s in all_skills:
        console.print(f"  [cyan]{s.name}[/cyan]: {s.description}")


@app.command()
def replay(session_id: str = typer.Argument(help="Session ID to replay")) -> None:
    """Replay a past agent session step by step."""
    from hive.memory.events import replay_session

    replay_session(session_id)


if __name__ == "__main__":
    app()
