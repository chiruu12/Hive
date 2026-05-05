"""Hive CLI — start the hive, watch agents live, nudge them."""

import asyncio
import signal
from pathlib import Path
from uuid import uuid4

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

app = typer.Typer(
    name="hive",
    help="Autonomous agent OS. Start the hive and watch agents come alive.",
    no_args_is_help=True,
)
console = Console()


@app.command()
def init() -> None:
    """Initialize a new hive in the current directory."""
    from hive.daemon.setup import initialize_hive

    hive_dir = Path.cwd() / ".hive"
    if hive_dir.exists():
        console.print("[dim]Hive already initialized.[/dim]")
        return
    initialize_hive()
    console.print("[green]✓ Hive initialized.[/green] Run `hive start` to bring agents alive.")


@app.command()
def start(
    heartbeat: int = typer.Option(10, "--heartbeat", "-b", help="Seconds between cycles"),
    profiles: str = typer.Option(
        "coder", "--profiles", "-p", help="Comma-separated profiles to spawn"
    ),
) -> None:
    """Start the hive daemon. Agents come alive autonomously."""
    from hive.agents.profile import AgentProfile
    from hive.agents.state import AgentState, AgentStatus
    from hive.daemon.loop import HiveDaemon
    from hive.memory.store import HiveStore

    hive_dir = Path.cwd() / ".hive"
    if not hive_dir.exists():
        console.print("[red]No .hive directory. Run `hive init` first.[/red]")
        raise typer.Exit(1)

    store = HiveStore(hive_dir / "hive.db")
    asyncio.run(store.initialize())

    profiles_dir = Path.cwd() / "profiles"
    profile_names = [p.strip() for p in profiles.split(",")]

    for name in profile_names:
        try:
            profile = AgentProfile.from_preset(name, profiles_dir)
            agent_id = f"{profile.name}-{uuid4().hex[:8]}"
            state = AgentState(
                agent_id=agent_id,
                name=profile.name,
                role=profile.role,
                model=profile.model,
                status=AgentStatus.IDLE,
                workspace=str(hive_dir / "workspaces" / agent_id),
            )
            asyncio.run(store.save_agent(state))
            console.print(f"  [green]✓[/green] Spawned {name} ({agent_id[:20]})")
        except FileNotFoundError:
            console.print(f"  [red]✗[/red] Profile not found: {name}")

    daemon = HiveDaemon(hive_dir, heartbeat=heartbeat)

    console.print(
        Panel(
            f"[bold]Hive is alive.[/bold]\n"
            f"  Heartbeat: {heartbeat}s\n"
            f"  Agents: {len(profile_names)}\n\n"
            f"[dim]Press Ctrl+C to stop.[/dim]",
            border_style="green",
        )
    )

    loop = asyncio.new_event_loop()

    def _stop(signum, frame):  # noqa: ANN001
        daemon.stop()
        console.print("\n[yellow]Stopping hive...[/yellow]")

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    try:
        loop.run_until_complete(daemon.start())
    except KeyboardInterrupt:
        pass
    finally:
        loop.close()
        console.print("[dim]Hive stopped.[/dim]")


@app.command()
def status() -> None:
    """Show who's alive, suffering levels, current goals."""
    from hive.memory.store import HiveStore

    hive_dir = Path.cwd() / ".hive"
    if not hive_dir.exists():
        console.print("[red]Run `hive init` first.[/red]")
        raise typer.Exit(1)

    store = HiveStore(hive_dir / "hive.db")
    agents = asyncio.run(store.list_agents())

    if not agents:
        console.print("[dim]No agents. Run `hive start` to bring them alive.[/dim]")
        return

    table = Table(title="Hive Agents")
    table.add_column("Agent", style="cyan")
    table.add_column("Role", style="dim", max_width=30)
    table.add_column("Model", style="green")
    table.add_column("Status")
    table.add_column("Goal", style="dim", max_width=40)

    status_styles = {
        "idle": "[dim]idle[/dim]",
        "working": "[bold yellow]working[/bold yellow]",
        "error": "[red]error[/red]",
        "dead": "[dim strikethrough]dead[/dim strikethrough]",
    }

    for a in agents:
        goal = asyncio.run(store.get_active_goal(a.agent_id))
        goal_text = goal["objective"][:40] if goal else "-"
        status_val = a.status.value if hasattr(a.status, "value") else a.status
        styled = status_styles.get(status_val, status_val)
        table.add_row(a.name, a.role, a.model, styled, goal_text)

    console.print(table)


@app.command()
def spawn(
    profile: str = typer.Argument(help="Profile to spawn (coder, reviewer, researcher, tester)"),
) -> None:
    """Add a new agent to the hive."""
    from hive.agents.profile import AgentProfile
    from hive.agents.state import AgentState, AgentStatus
    from hive.memory.store import HiveStore

    hive_dir = Path.cwd() / ".hive"
    if not hive_dir.exists():
        console.print("[red]Run `hive init` first.[/red]")
        raise typer.Exit(1)

    profiles_dir = Path.cwd() / "profiles"
    try:
        p = AgentProfile.from_preset(profile, profiles_dir)
    except FileNotFoundError:
        console.print(f"[red]Profile not found: {profile}[/red]")
        raise typer.Exit(1)

    agent_id = f"{p.name}-{uuid4().hex[:8]}"
    state = AgentState(
        agent_id=agent_id,
        name=p.name,
        role=p.role,
        model=p.model,
        status=AgentStatus.IDLE,
        workspace=str(hive_dir / "workspaces" / agent_id),
    )
    store = HiveStore(hive_dir / "hive.db")
    asyncio.run(store.save_agent(state))
    console.print(f"[green]✓ Spawned[/green] {p.name} ({agent_id})")


@app.command()
def kill(agent: str = typer.Argument(help="Agent name or ID to terminate")) -> None:
    """Remove an agent from the hive."""
    from hive.agents.state import AgentStatus
    from hive.memory.store import HiveStore

    hive_dir = Path.cwd() / ".hive"
    if not hive_dir.exists():
        console.print("[red]Run `hive init` first.[/red]")
        raise typer.Exit(1)

    store = HiveStore(hive_dir / "hive.db")
    agents = asyncio.run(store.list_agents())
    target = None
    for a in agents:
        if a.agent_id == agent or a.name == agent or a.agent_id.startswith(agent):
            target = a
            break
    if not target:
        console.print(f"[red]Agent not found: {agent}[/red]")
        raise typer.Exit(1)

    asyncio.run(store.update_agent_status(target.agent_id, AgentStatus.DEAD))
    console.print(f"[red]✗ Killed[/red] {target.name} ({target.agent_id})")


@app.command()
def nudge(
    agent: str = typer.Argument(help="Agent name or ID"),
    message: str = typer.Argument(help="Direction to give the agent"),
) -> None:
    """Give occasional direction to an agent."""
    from hive.memory.store import HiveStore

    hive_dir = Path.cwd() / ".hive"
    if not hive_dir.exists():
        console.print("[red]Run `hive init` first.[/red]")
        raise typer.Exit(1)

    store = HiveStore(hive_dir / "hive.db")
    agents = asyncio.run(store.list_agents())
    target = None
    for a in agents:
        if a.agent_id == agent or a.name == agent or a.agent_id.startswith(agent):
            target = a
            break
    if not target:
        console.print(f"[red]Agent not found: {agent}[/red]")
        raise typer.Exit(1)

    nudge_id = f"nudge-{uuid4().hex[:8]}"
    asyncio.run(store.save_nudge(nudge_id, target.agent_id, message))
    console.print(f"[blue]→ Nudged[/blue] {target.name}: {message}")


@app.command()
def watch() -> None:
    """Live stream of agent activity."""
    from hive.memory.events import EventLog

    hive_dir = Path.cwd() / ".hive"
    if not hive_dir.exists():
        console.print("[red]Run `hive init` first.[/red]")
        raise typer.Exit(1)

    console.print("[bold]Watching hive activity...[/bold] (Ctrl+C to stop)\n")

    event_log = EventLog(hive_dir)
    store_path = hive_dir / "hive.db"

    from hive.memory.store import HiveStore

    store = HiveStore(store_path)
    agents = asyncio.run(store.list_agents())

    if not agents:
        console.print("[dim]No agents found.[/dim]")
        return

    from hive.memory.events import _print_event

    async def _watch_all() -> None:
        tasks = []
        for a in agents:
            tasks.append(_watch_agent(event_log, a.agent_id))
        await asyncio.gather(*tasks)

    async def _watch_agent(elog: EventLog, agent_id: str) -> None:
        async for event in elog.stream(agent_id):
            _print_event(console, event)

    try:
        asyncio.run(_watch_all())
    except KeyboardInterrupt:
        pass


@app.command()
def models() -> None:
    """Show available models."""
    from hive.models.router import detect_models

    available = detect_models()
    for provider, model_list in available.items():
        console.print(f"\n[bold]{provider}[/bold]:")
        for m in model_list:
            s = "[green]available[/green]" if m.available else "[red]unavailable[/red]"
            console.print(f"  {m.name}: {s}")


@app.command()
def replay(session_id: str = typer.Argument(help="Session ID to replay")) -> None:
    """Replay a past session step by step."""
    from hive.memory.events import replay_session

    replay_session(session_id)


if __name__ == "__main__":
    app()
