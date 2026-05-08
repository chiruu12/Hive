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

    daemon = HiveDaemon(
        hive_dir,
        heartbeat=heartbeat,
        logs_dir=Path.cwd() / "logs",
        profiles=profile_names,
    )

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
    """Live TUI dashboard showing agent activity."""
    from collections import deque

    from rich.layout import Layout
    from rich.live import Live

    from hive.memory.events import EventType, HiveEvent
    from hive.memory.store import HiveStore

    hive_dir = Path.cwd() / ".hive"
    if not hive_dir.exists():
        console.print("[red]Run `hive init` first.[/red]")
        raise typer.Exit(1)

    store = HiveStore(hive_dir / "hive.db")
    feed: deque[str] = deque(maxlen=20)

    def _build_dashboard() -> Layout:
        agents = asyncio.run(store.list_agents())
        alive = [a for a in agents if a.is_alive()]

        agent_table = Table(title="Agents", box=None, show_edge=False, pad_edge=False)
        agent_table.add_column("Name", style="cyan", width=12)
        agent_table.add_column("Status", width=10)
        agent_table.add_column("Goal", style="dim", max_width=50)

        status_styles = {
            "idle": "[dim]idle[/dim]",
            "working": "[bold yellow]working[/bold yellow]",
            "error": "[red]error[/red]",
        }

        for a in alive:
            goal = asyncio.run(store.get_active_goal(a.agent_id))
            goal_text = goal["objective"][:50] if goal else "-"
            sv = a.status.value if hasattr(a.status, "value") else a.status
            agent_table.add_row(a.name, status_styles.get(sv, sv), goal_text)

        feed_text = "\n".join(feed) if feed else "[dim]Waiting for events...[/dim]"

        layout = Layout()
        layout.split_column(
            Layout(
                Panel(agent_table, title="Hive Agents", border_style="green"),
                name="top",
                size=len(alive) + 5,
            ),
            Layout(
                Panel(feed_text, title="Activity Feed", border_style="blue"),
                name="bottom",
            ),
        )
        return layout

    def _format_event(event: HiveEvent) -> str:
        ts = event.ts.strftime("%H:%M:%S")
        name = event.agent_id.split("-")[0]
        et = event.event_type

        if et == EventType.TOOL_USED:
            tool = event.data.get("tool", "?")
            return f"[cyan]{ts}[/cyan] {name} [dim]⚡[/dim] {tool}"
        if et == EventType.GOAL_SET:
            obj = (event.data.get("objective") or "")[:50]
            return f"[blue]{ts}[/blue] {name} [bold]🎯[/bold] {obj}"
        if et == EventType.GOAL_COMPLETED:
            return f"[green]{ts}[/green] {name} [bold]✓[/bold] goal completed"
        if et == EventType.GOAL_ABANDONED:
            return f"[red]{ts}[/red] {name} [bold]✗[/bold] goal abandoned"
        if et == EventType.SUFFERING_CHANGED:
            load = event.data.get("load", 0)
            if load > 0:
                bar_len = int(load * 10)
                bar = "█" * bar_len + "░" * (10 - bar_len)
                return f"[yellow]{ts}[/yellow] {name} [{bar}] {load:.0%}"
            return ""
        if et == EventType.ERROR:
            msg = (event.data.get("message") or "")[:60]
            return f"[red]{ts}[/red] {name} ✗ {msg}"
        if et == EventType.ASSISTANT_MESSAGE:
            text = (event.data.get("text") or "")[:60]
            return f"[white]{ts}[/white] {name} 💬 {text}"
        return ""

    async def _poll_events() -> None:
        agents = asyncio.run(store.list_agents())
        offsets: dict[str, int] = {}

        while True:
            for a in agents:
                if not a.is_alive():
                    continue
                agent_dir = hive_dir / "sessions" / a.agent_id
                if not agent_dir.exists():
                    continue
                sessions = sorted(
                    agent_dir.glob("*.jsonl"),
                    key=lambda p: p.stat().st_mtime,
                )
                if not sessions:
                    continue
                path = sessions[-1]
                offset = offsets.get(a.agent_id, 0)
                text = path.read_text()
                new_lines = text[offset:].strip().splitlines()
                for line in new_lines:
                    if line.strip():
                        try:
                            ev = HiveEvent.from_jsonl(line)
                            formatted = _format_event(ev)
                            if formatted:
                                feed.append(formatted)
                        except Exception:
                            pass
                offsets[a.agent_id] = len(text)
            await asyncio.sleep(0.5)

    try:
        with Live(_build_dashboard(), console=console, refresh_per_second=2) as live:

            async def _run() -> None:
                poll_task = asyncio.create_task(_poll_events())
                try:
                    while True:
                        live.update(_build_dashboard())
                        await asyncio.sleep(0.5)
                finally:
                    poll_task.cancel()

            asyncio.run(_run())
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


@app.command()
def runs() -> None:
    """List all recorded runs with summary stats."""
    from hive.logging.reader import LogReader

    logs_dir = Path.cwd() / "logs"
    reader = LogReader(logs_dir)
    all_runs = reader.list_runs()

    if not all_runs:
        console.print("[dim]No runs recorded yet. Start the hive to create a run.[/dim]")
        return

    table = Table(title="Recorded Runs")
    table.add_column("Run ID", style="cyan")
    table.add_column("Started", style="dim")
    table.add_column("Heartbeat")
    table.add_column("Agents", style="green")
    table.add_column("Profiles")

    for r in all_runs:
        table.add_row(
            r.run_id,
            r.started_at.strftime("%Y-%m-%d %H:%M"),
            f"{r.heartbeat}s",
            str(len(r.agents_spawned)),
            ", ".join(r.profiles),
        )

    console.print(table)


@app.command()
def inspect(run_id: str = typer.Argument(help="Run ID to inspect")) -> None:
    """Show detailed summary of a recorded run."""
    from hive.logging.reader import LogReader

    logs_dir = Path.cwd() / "logs"
    reader = LogReader(logs_dir)
    summary = reader.get_summary(run_id)

    if not summary:
        console.print(f"[red]Run not found: {run_id}[/red]")
        raise typer.Exit(1)

    console.print(
        Panel(
            f"[bold]Run:[/bold] {summary['run_id']}\n"
            f"  Started: {summary['started_at']}\n"
            f"  Heartbeat: {summary['heartbeat']}s\n"
            f"  Agents: {summary['agents']}\n\n"
            f"[bold]Goals:[/bold]\n"
            f"  Generated: {summary['goals_generated']}\n"
            f"  Completed: {summary['goals_completed']}\n"
            f"  Abandoned: {summary['goals_abandoned']}\n\n"
            f"[bold]Activity:[/bold]\n"
            f"  Tool calls: {summary['tool_calls']}\n"
            f"  Total tokens: {summary['total_tokens']:,}\n"
            f"  Total cost: ${summary['total_cost_usd']:.4f}",
            title="Run Summary",
            border_style="blue",
        )
    )

    for aid in summary["agent_ids"]:
        goals = reader.get_agent_goals(run_id, aid)
        decisions = reader.get_agent_decisions(run_id, aid)
        tools = reader.get_agent_tools(run_id, aid)

        console.print(f"\n  [cyan]{aid}[/cyan]:")
        console.print(f"    Goals: {len(goals)}, Decisions: {len(decisions)}, Tools: {len(tools)}")

        for g in goals[:5]:
            status_icon = {"generated": "🎯", "completed": "✓", "abandoned": "✗"}.get(g.event, "·")
            obj = (g.objective or "")[:60]
            console.print(f"    {status_icon} [{g.event}] {obj}")


@app.command()
def lives() -> None:
    """List all agent life directories."""
    from hive.world.life_summary import LifeDirectoryWriter

    hive_dir = Path.cwd() / ".hive"
    if not hive_dir.exists():
        console.print("[red]Run `hive init` first.[/red]")
        raise typer.Exit(1)

    writer = LifeDirectoryWriter(hive_dir)
    agent_ids = writer.list_lives()

    if not agent_ids:
        console.print("[dim]No life records yet. Run the hive first.[/dim]")
        return

    table = Table(title="Agent Lives")
    table.add_column("Agent", style="cyan")
    table.add_column("Name", style="bold")
    table.add_column("Money")
    table.add_column("Stats")
    table.add_column("Events")

    for aid in agent_ids:
        summary = writer.read(aid)
        if not summary:
            continue
        stats_str = " ".join(f"{k}:{v:.0%}" for k, v in summary.final_stats.items())
        table.add_row(
            aid[:20],
            summary.display_name,
            f"${summary.final_money:.0f}",
            stats_str,
            str(len(summary.milestones)),
        )

    console.print(table)


@app.command()
def biography(
    agent: str = typer.Argument(help="Agent name or ID"),
) -> None:
    """Show the full biography of an agent's life."""
    from hive.world.life_summary import LifeDirectoryWriter

    hive_dir = Path.cwd() / ".hive"
    if not hive_dir.exists():
        console.print("[red]Run `hive init` first.[/red]")
        raise typer.Exit(1)

    writer = LifeDirectoryWriter(hive_dir)
    agent_ids = writer.list_lives()

    exact = [aid for aid in agent_ids if aid == agent]
    if exact:
        target = exact[0]
    else:
        prefix = [aid for aid in agent_ids if aid.startswith(agent)]
        if len(prefix) == 1:
            target = prefix[0]
        elif len(prefix) > 1:
            console.print(f"[red]Ambiguous match for '{agent}': {prefix}[/red]")
            raise typer.Exit(1)
        else:
            target = None

    if not target:
        console.print(f"[red]No life record found for: {agent}[/red]")
        raise typer.Exit(1)

    bio = writer.read_biography(target)
    if not bio:
        console.print(f"[red]No biography available for: {target}[/red]")
        raise typer.Exit(1)

    from rich.markdown import Markdown

    console.print(Markdown(bio))


if __name__ == "__main__":
    app()
