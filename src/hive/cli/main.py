"""Hive CLI — start the hive, watch agents live, nudge them."""

import asyncio
import signal
from datetime import datetime
from pathlib import Path
from typing import Any
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
    fresh: bool = typer.Option(False, "--fresh", help="Ignore saved state, start clean"),
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

    existing = asyncio.run(store.list_agents())
    resumable = [a for a in existing if a.status != AgentStatus.DEAD]
    resuming = not fresh and len(resumable) > 0

    profiles_dir = Path.cwd() / "profiles"
    profile_names = [p.strip() for p in profiles.split(",")]

    if resuming:
        console.print(f"[cyan]Resuming {len(resumable)} agents from previous run.[/cyan]")
    else:
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
        fresh=fresh,
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

    def _stop(signum: int, frame: object) -> None:
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
        "waiting_approval": "[magenta]waiting approval[/magenta]",
        "error": "[red]error[/red]",
        "dead": "[dim strikethrough]dead[/dim strikethrough]",
    }

    for a in agents:
        goal = asyncio.run(store.get_active_goal(a.agent_id))
        goal_text = goal["objective"][:40] if goal else "-"
        status_val = a.status.value if hasattr(a.status, "value") else a.status
        styled = status_styles.get(status_val, status_val)
        name_display = f"[sub] {a.name}" if a.spawned_by else a.name
        table.add_row(name_display, a.role, a.model, styled, goal_text)

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
def watch(
    compact: bool = typer.Option(False, "--compact", help="2-panel layout for small terminals"),
    screenshot: str = typer.Option("", "--screenshot", help="Directory to save TUI screenshots"),
    screenshot_interval: int = typer.Option(
        10, "--screenshot-interval", help="Seconds between screenshots"
    ),
) -> None:
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
    feed: deque[str] = deque(maxlen=30)
    drama: deque[str] = deque(maxlen=10)
    suffering_cache: dict[str, float] = {}
    vitals: dict[str, dict[str, int | float]] = {}

    def _suffering_bar(load: float) -> str:
        bar_len = int(load * 10)
        return "█" * bar_len + "░" * (10 - bar_len)

    def _happiness_emoji(h: float) -> str:
        if h >= 0.6:
            return "\U0001f60a"
        if h >= 0.3:
            return "\U0001f610"
        return "\U0001f622"

    async def _build_dashboard() -> Layout:
        agents = await store.list_agents()
        alive = [a for a in agents if a.is_alive()]

        agent_table = Table(box=None, show_edge=False, pad_edge=False)
        agent_table.add_column("Agent", style="cyan", width=18)
        agent_table.add_column("Status", width=10)
        agent_table.add_column("Goal", style="dim", max_width=35)
        agent_table.add_column("Suffering", width=14)
        agent_table.add_column("", width=5)

        status_styles = {
            "idle": "[dim]idle[/dim]",
            "working": "[bold yellow]working[/bold yellow]",
            "waiting_approval": "[magenta]waiting approval[/magenta]",
            "error": "[red]error[/red]",
        }

        for a in alive:
            goal = await store.get_active_goal(a.agent_id)
            goal_text = goal["objective"][:35] if goal else "-"
            sv = a.status.value if hasattr(a.status, "value") else a.status
            styled = status_styles.get(sv, sv)
            name_display = a.name
            if a.spawned_by:
                parent_name = a.spawned_by.split("-")[0]
                name_display = f"[dim][sub→{parent_name}][/dim] {a.name}"

            load = suffering_cache.get(a.agent_id, 0.0)
            suf_bar = _suffering_bar(load)
            suf_text = f"[{suf_bar}] {load:.0%}" if load > 0 else "[dim]-[/dim]"

            indicators = ""
            v = vitals.get(a.agent_id, {})
            risk = v.get("risk_tolerance", 0.3)
            happiness = v.get("happiness", 0.7)
            if isinstance(risk, float) and risk > 0.6:
                indicators += "\U0001f3b2"
            if isinstance(happiness, float):
                indicators += _happiness_emoji(happiness)

            agent_table.add_row(name_display, styled, goal_text, suf_text, indicators)

        feed_text = "\n".join(feed) if feed else "[dim]Waiting for events...[/dim]"

        layout = Layout()

        if compact:
            layout.split_column(
                Layout(
                    Panel(agent_table, title="Hive Agents", border_style="green"),
                    name="agents",
                    size=max(len(alive) + 4, 6),
                ),
                Layout(
                    Panel(feed_text, title="Activity Feed", border_style="blue"),
                    name="feed",
                ),
            )
        else:
            vitals_lines = []
            for a in alive:
                v = vitals.get(a.agent_id, {})
                tokens = v.get("tokens", 0)
                cost = v.get("cost", 0.0)
                done = v.get("goals_done", 0)
                abandoned = v.get("goals_abandoned", 0)
                money = v.get("money", 0)
                line = (
                    f"[cyan]{a.name[:12]:12s}[/cyan] "
                    f"tok:{tokens:>6,} "
                    f"${cost:>5.3f} "
                    f"done:{done} "
                    f"fail:{abandoned} "
                    f"${money}"
                )
                vitals_lines.append(line)
            vitals_text = "\n".join(vitals_lines) if vitals_lines else "[dim]-[/dim]"

            drama_text = "\n".join(drama) if drama else "[dim]No drama yet...[/dim]"

            top = Layout(name="top", size=max(len(alive) + 4, 6))
            top.update(
                Panel(agent_table, title="Hive Agents", border_style="green"),
            )

            middle = Layout(name="middle")
            middle.split_row(
                Layout(
                    Panel(feed_text, title="Activity Feed", border_style="blue"),
                    name="feed",
                ),
                Layout(
                    Panel(drama_text, title="Drama", border_style="magenta"),
                    name="drama",
                    size=45,
                ),
            )

            bottom = Layout(
                Panel(vitals_text, title="Vitals", border_style="dim"),
                name="bottom",
                size=max(len(alive) + 3, 4),
            )

            layout.split_column(top, middle, bottom)

        return layout

    def _format_event(event: HiveEvent) -> str:
        ts = event.ts.strftime("%H:%M:%S")
        name = event.agent_id.split("-")[0]
        et = event.event_type

        if et == EventType.TOOL_USED:
            tool_name = event.data.get("tool", "?")
            return f"[cyan]{ts}[/cyan] {name} ⚡ {tool_name}"
        if et == EventType.GOAL_SET:
            obj = (event.data.get("objective") or "")[:50]
            return f"[blue]{ts}[/blue] {name} \U0001f3af {obj}"
        if et == EventType.GOAL_COMPLETED:
            return f"[green]{ts}[/green] {name} ✓ goal completed"
        if et == EventType.GOAL_ABANDONED:
            return f"[red]{ts}[/red] {name} ✗ goal abandoned"
        if et == EventType.SUFFERING_CHANGED:
            load = event.data.get("load", 0)
            prev = suffering_cache.get(event.agent_id, 0)
            suffering_cache[event.agent_id] = load
            if load > 0:
                bar = _suffering_bar(load)
                line = f"[yellow]{ts}[/yellow] {name} [{bar}] {load:.0%}"
                delta = load - prev
                if abs(delta) > 0.15:
                    direction = "spiked" if delta > 0 else "dropped"
                    drama.append(
                        f"[yellow]{ts}[/yellow] {name}'s suffering {direction}! "
                        f"{prev:.0%}→{load:.0%}"
                    )
                return line
            return ""
        if et == EventType.EXISTENCE_CYCLE:
            life_event = event.data.get("life_event")
            if life_event:
                choice = event.data.get("choice", "")[:40]
                line = f"[magenta]{ts}[/magenta] {name} \U0001f3ad {life_event}: {choice}"
                drama.append(line)
                return line
            persona_change = event.data.get("persona_change")
            if persona_change:
                drama.append(f"[cyan]{ts}[/cyan] {name} {persona_change}")
            return ""
        if et == EventType.ERROR:
            msg = (event.data.get("message") or "")[:60]
            return f"[red]{ts}[/red] {name} ✗ {msg}"
        if et == EventType.ASSISTANT_MESSAGE:
            text = (event.data.get("text") or "")[:60]
            return f"[white]{ts}[/white] {name} \U0001f4ac {text}"
        return ""

    async def _poll_events() -> None:
        agents = await store.list_agents()
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
                try:
                    text = path.read_text()
                except OSError:
                    continue
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

            try:
                agents = await store.list_agents()
            except Exception:
                pass
            await asyncio.sleep(0.5)

    screenshot_dir = Path(screenshot) if screenshot else None
    if screenshot_dir:
        screenshot_dir.mkdir(parents=True, exist_ok=True)

    async def _watch_loop() -> None:
        await store.initialize()
        last_screenshot = 0.0
        with Live(await _build_dashboard(), console=console, refresh_per_second=2) as live:
            poll_task = asyncio.create_task(_poll_events())
            try:
                while True:
                    dashboard = await _build_dashboard()
                    live.update(dashboard)

                    if screenshot_dir:
                        import time

                        now = time.time()
                        if now - last_screenshot >= screenshot_interval:
                            last_screenshot = now
                            ts = datetime.now().strftime("%H%M%S")
                            path = screenshot_dir / f"screenshot-{ts}.txt"
                            capture = Console(
                                file=open(path, "w"),  # noqa: SIM115
                                width=120,
                                force_terminal=True,
                            )
                            capture.print(dashboard)
                            capture.file.close()

                    await asyncio.sleep(0.5)
            finally:
                poll_task.cancel()

    try:
        asyncio.run(_watch_loop())
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
            if m.available:
                s = "[green]available[/green]"
            else:
                reason = f" ({m.detail.replace('_', ' ')})" if m.detail else ""
                s = f"[red]unavailable[/red]{reason}"
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


@app.command()
def benchmark(
    models: str = typer.Argument(help="Comma-separated models to compare"),
    task: str = typer.Option(
        "", "--task", "-t", help="Single task to run (default: goal generation)"
    ),
    cycles: int = typer.Option(5, "--cycles", "-c", help="Cycles per model"),
    runs: int = typer.Option(1, "--runs", "-n", help="Runs per model"),
    output: str = typer.Option("", "--output", "-o", help="Save JSON results to file"),
) -> None:
    """Compare models on the same scenario."""
    from hive.benchmark.report import BenchmarkReport
    from hive.benchmark.runner import BenchmarkRunner

    hive_dir = Path.cwd() / ".hive"
    if not hive_dir.exists():
        console.print("[red]Run `hive init` first.[/red]")
        raise typer.Exit(1)

    model_list = [m.strip() for m in models.split(",")]
    runner = BenchmarkRunner(hive_dir)

    if task:
        result = asyncio.run(runner.run_task_benchmark(model_list, task=task, runs=runs))
    else:
        result = asyncio.run(runner.run_goal_benchmark(model_list, cycles=cycles, runs=runs))

    report = BenchmarkReport(result)
    report.print_table(console)

    if output:
        path = report.save_json(Path(output))
        console.print(f"[green]Results saved to {path}[/green]")


@app.command()
def export(
    run_id: str = typer.Argument(help="Run ID to export"),
    output: str = typer.Option("", "--output", "-o", help="Output file path"),
) -> None:
    """Export a run as a standalone HTML report."""
    from hive.export.html import export_html_report

    logs_dir = Path.cwd() / "logs"
    hive_dir = Path.cwd() / ".hive"
    if not logs_dir.exists():
        console.print("[red]No logs directory found.[/red]")
        raise typer.Exit(1)

    out_path = Path(output) if output else Path.cwd() / f"hive-report-{run_id}.html"
    try:
        result = export_html_report(
            run_id,
            logs_dir,
            out_path,
            hive_dir=hive_dir if hive_dir.exists() else None,
        )
        console.print(f"[green]✓ Report exported:[/green] {result}")
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)


@app.command()
def doctor() -> None:
    """Check environment health and diagnose common issues."""
    from hive.daemon.diagnostics import run_all_checks

    hive_dir = Path.cwd() / ".hive"
    checks = run_all_checks(hive_dir)

    status_icons = {
        "ok": "[green]OK[/green]",
        "warn": "[yellow]WARN[/yellow]",
        "fail": "[red]FAIL[/red]",
    }

    table = Table(title="Hive Doctor", show_lines=False)
    table.add_column("Check", style="bold")
    table.add_column("Status")
    table.add_column("Details", style="dim")

    for c in checks:
        table.add_row(c.name, status_icons[c.status], c.message)

    console.print(table)

    fixes = [c for c in checks if c.fix and c.status in ("warn", "fail")]
    if fixes:
        console.print("\n[bold]Suggestions:[/bold]")
        for c in fixes:
            icon = "[red]![/red]" if c.status == "fail" else "[yellow]?[/yellow]"
            console.print(f"  {icon} {c.name}: {c.fix}")

    fails = sum(1 for c in checks if c.status == "fail")
    if fails:
        console.print(f"\n[red]{fails} critical issue(s) found.[/red]")
    else:
        console.print("\n[green]All checks passed or optional.[/green]")


@app.command()
def journal(
    agent: str = typer.Argument(help="Agent name or ID"),
) -> None:
    """Read an agent's notepad."""
    from hive.tools.notepad import NotepadManager

    hive_dir = Path.cwd() / ".hive"
    if not hive_dir.exists():
        console.print("[red]Run `hive init` first.[/red]")
        raise typer.Exit(1)

    manager = NotepadManager(hive_dir)
    agents_with_journals = manager.list_agents_with_journals()

    target = None
    for aid in agents_with_journals:
        if aid == agent or aid.startswith(agent):
            target = aid
            break

    if not target:
        console.print(f"[red]No notepad found for: {agent}[/red]")
        raise typer.Exit(1)

    content = manager.read(target)
    if not content.strip():
        console.print(f"[dim]Notepad is empty for {target}[/dim]")
        return

    from rich.markdown import Markdown

    console.print(Panel(Markdown(content), title=f"Notepad — {target}", border_style="blue"))


@app.command()
def journals() -> None:
    """List all agents with notepads."""
    from hive.tools.notepad import NotepadManager

    hive_dir = Path.cwd() / ".hive"
    if not hive_dir.exists():
        console.print("[red]Run `hive init` first.[/red]")
        raise typer.Exit(1)

    manager = NotepadManager(hive_dir)
    agents = manager.list_agents_with_journals()

    if not agents:
        console.print("[dim]No notepads yet. Run the hive first.[/dim]")
        return

    table = Table(title="Agent Notepads")
    table.add_column("Agent", style="cyan")
    table.add_column("Entries", style="dim")

    for aid in agents:
        notepad = manager.read(aid)
        entry_count = notepad.count("---") if notepad.strip() else 0
        table.add_row(aid[:25], str(entry_count))

    console.print(table)


@app.command()
def messages(
    agent: str = typer.Argument(help="Agent name or ID"),
    outbox: bool = typer.Option(False, "--outbox", help="Show outbox instead of inbox"),
) -> None:
    """Show an agent's A2A messages."""
    from hive.interactions.a2a import A2AStore
    from hive.memory.store import HiveStore

    hive_dir = Path.cwd() / ".hive"
    if not hive_dir.exists():
        console.print("[red]Run `hive init` first.[/red]")
        raise typer.Exit(1)

    a2a = A2AStore(hive_dir)
    store = HiveStore(hive_dir / "hive.db")
    agents = asyncio.run(store.list_agents())
    target = None
    for a in agents:
        if a.agent_id == agent or a.name == agent or a.agent_id.startswith(agent):
            target = a.agent_id
            break
    if not target:
        console.print(f"[red]Agent not found: {agent}[/red]")
        raise typer.Exit(1)

    if outbox:
        msgs = asyncio.run(a2a.get_outbox(target))
        title = f"Outbox — {target}"
    else:
        msgs = asyncio.run(a2a.get_inbox(target))
        title = f"Inbox — {target}"

    if not msgs:
        console.print(f"[dim]{title}: empty[/dim]")
        return

    table = Table(title=title)
    table.add_column("ID", style="cyan", max_width=15)
    table.add_column("Type", style="dim")
    table.add_column("From/To")
    table.add_column("Subject", max_width=40)
    table.add_column("Time", style="dim")

    for m in msgs:
        peer = m.from_agent if not outbox else m.to_agent
        ts = m.ts.strftime("%H:%M:%S")
        table.add_row(m.message_id, m.type, peer[:20], m.subject[:40], ts)

    console.print(table)


@app.command()
def threads(
    agent: str = typer.Argument(None, help="Agent name or ID (optional)"),
) -> None:
    """Show active message threads."""
    from hive.interactions.a2a import A2AStore
    from hive.memory.store import HiveStore

    hive_dir = Path.cwd() / ".hive"
    if not hive_dir.exists():
        console.print("[red]Run `hive init` first.[/red]")
        raise typer.Exit(1)

    a2a = A2AStore(hive_dir)
    store = HiveStore(hive_dir / "hive.db")
    agents = asyncio.run(store.list_agents())

    target_ids = []
    if agent:
        for a in agents:
            if a.agent_id == agent or a.name == agent or a.agent_id.startswith(agent):
                target_ids.append(a.agent_id)
                break
    else:
        target_ids = [a.agent_id for a in agents]

    if not target_ids:
        console.print("[dim]No agents found.[/dim]")
        return

    seen_threads: set[str] = set()
    for aid in target_ids:
        inbox = asyncio.run(a2a.get_inbox(aid, limit=50))
        for m in inbox:
            root = m.reply_to or m.message_id
            if root not in seen_threads:
                seen_threads.add(root)
                thread = asyncio.run(a2a.get_thread(aid, root))
                if len(thread) > 1:
                    console.print(f"\n[cyan]Thread {root}[/cyan] ({len(thread)} messages):")
                    for t in thread:
                        ts = t.ts.strftime("%H:%M:%S")
                        console.print(
                            f"  [{ts}] {t.from_agent} → {t.to_agent}: [{t.type}] {t.subject[:50]}"
                        )

    if not seen_threads:
        console.print("[dim]No threads found.[/dim]")


@app.command()
def orchestrate(
    task: str = typer.Argument(help="High-level coding task to orchestrate"),
    workspace: str = typer.Option(".", "--workspace", "-w", help="Project directory"),
    tool: str = typer.Option("claude", "--tool", "-t", help="CLI tool: claude or codex"),
    model: str = typer.Option("sonnet", "--model", "-m", help="Model to use for subtasks"),
) -> None:
    """Orchestrate a complex coding task by breaking it into subtasks."""
    import shutil

    from hive.models.factory import create_runtime_provider
    from hive.orchestrator.manager import SessionManager
    from hive.orchestrator.toolkit import OrchestratorToolkit
    from hive.runtime.agent import Agent
    from hive.runtime.persona import Persona

    workspace_path = Path(workspace).resolve()
    if not workspace_path.is_dir():
        console.print(f"[red]Workspace not found: {workspace}[/red]")
        raise typer.Exit(1)

    if tool == "claude" and not shutil.which("claude"):
        console.print("[red]Claude Code CLI not found. Install it first.[/red]")
        raise typer.Exit(1)
    if tool == "codex" and not shutil.which("codex"):
        console.print("[red]Codex CLI not found. Install it first.[/red]")
        raise typer.Exit(1)

    hive_dir = Path.cwd() / ".hive"
    if not hive_dir.exists():
        hive_dir.mkdir(parents=True)

    manager = SessionManager(hive_dir)
    orch_toolkit = OrchestratorToolkit(manager)

    persona = Persona(
        name="Orchestrator",
        purpose="Break down and delegate coding tasks",
        personality=["systematic", "thorough"],
        instructions=[
            f"You are orchestrating the following task: {task}",
            f"The workspace is: {workspace_path}",
            f"Use the '{tool}' CLI tool with model '{model}' for each subtask.",
            "Break the main task into clear, independent subtasks.",
            "Run each subtask using run_code_task.",
            "Review the output of each completed task.",
            "Provide a final summary of all results.",
        ],
    )

    provider = create_runtime_provider("claude-haiku-4-5")
    agent = Agent(
        name="orchestrator",
        model=provider,
        persona=persona,
        toolkits=[orch_toolkit],
        max_steps=50,
    )

    console.print(
        Panel(
            f"[bold]Orchestrating:[/bold] {task}\n"
            f"  Workspace: {workspace_path}\n"
            f"  Tool: {tool}\n"
            f"  Model: {model}\n\n"
            f"[dim]This may take several minutes...[/dim]",
            border_style="blue",
        )
    )

    async def _run() -> str:
        return await agent.run_once(
            f"Execute this task by breaking it into subtasks and running each one: {task}",
            max_tool_rounds=20,
        )

    try:
        result = asyncio.run(_run())
        console.print()
        from rich.markdown import Markdown

        console.print(Panel(Markdown(result), title="Orchestration Complete", border_style="green"))
    except KeyboardInterrupt:
        console.print("\n[yellow]Orchestration cancelled.[/yellow]")
    except Exception as e:
        console.print(f"\n[red]Orchestration failed: {e}[/red]")
        raise typer.Exit(1)


tasks_app = typer.Typer(
    name="tasks",
    help="Manage agent tasks.",
    invoke_without_command=True,
)
app.add_typer(tasks_app, name="tasks")


@tasks_app.callback()
def tasks_list(
    ctx: typer.Context,
    status: str = typer.Option("pending", "--status", "-s", help="Filter by status"),
) -> None:
    """List tasks across all agents."""
    if ctx.invoked_subcommand is not None:
        return
    from hive.memory.store import HiveStore

    hive_dir = Path.cwd() / ".hive"
    if not hive_dir.exists():
        console.print("[red]Run `hive init` first.[/red]")
        raise typer.Exit(1)

    store = HiveStore(hive_dir / "hive.db")
    asyncio.run(store.initialize())
    tasks = asyncio.run(store.list_all_tasks(status))
    if not tasks:
        console.print(f"[dim]No {status} tasks.[/dim]")
        return

    table = Table(title=f"{status.title()} Tasks")
    table.add_column("ID", style="cyan")
    table.add_column("Agent", style="dim")
    table.add_column("Description")
    table.add_column("Priority")
    table.add_column("Due", style="dim")

    for t in tasks:
        table.add_row(
            t["task_id"],
            t["agent_id"].split("-")[0],
            t["description"][:60],
            t["priority"],
            t["due_date"] or "-",
        )
    console.print(table)


@tasks_app.command("done")
def tasks_done(task_id: str = typer.Argument(help="Task ID to complete")) -> None:
    """Mark a task as done."""
    from hive.memory.store import HiveStore

    hive_dir = Path.cwd() / ".hive"
    if not hive_dir.exists():
        console.print("[red]Run `hive init` first.[/red]")
        raise typer.Exit(1)

    store = HiveStore(hive_dir / "hive.db")
    asyncio.run(store.initialize())
    ok = asyncio.run(store.complete_task(task_id))
    if ok:
        console.print(f"[green]✓ Task {task_id} completed.[/green]")
    else:
        console.print(f"[red]Task {task_id} not found or already done.[/red]")


notes_app = typer.Typer(
    name="notes",
    help="Browse and search knowledge notes.",
    invoke_without_command=True,
)
app.add_typer(notes_app, name="notes")


@notes_app.callback()
def notes_list(
    ctx: typer.Context,
    limit: int = typer.Option(10, "--limit", "-n", help="Number of notes"),
) -> None:
    """List recent notes across all agents."""
    if ctx.invoked_subcommand is not None:
        return
    from hive.memory.semantic import SemanticMemory

    hive_dir = Path.cwd() / ".hive"
    if not hive_dir.exists():
        console.print("[red]Run `hive init` first.[/red]")
        raise typer.Exit(1)

    memory_dir = hive_dir / "memory"
    if not memory_dir.exists():
        console.print("[dim]No notes yet.[/dim]")
        return

    all_notes: list[tuple[str, Any]] = []
    for agent_dir in memory_dir.iterdir():
        if agent_dir.is_dir():
            mem = SemanticMemory(hive_dir, agent_dir.name)
            all_notes.extend((agent_dir.name, n) for n in mem.recent(limit))
    all_notes.sort(key=lambda x: x[1].ts, reverse=True)

    if not all_notes:
        console.print("[dim]No notes yet.[/dim]")
        return

    table = Table(title="Recent Notes")
    table.add_column("ID", style="cyan")
    table.add_column("Agent", style="dim")
    table.add_column("Content")
    table.add_column("Tags", style="dim")
    table.add_column("Time", style="dim")

    for agent, note in all_notes[:limit]:
        table.add_row(
            note.memory_id,
            agent.split("-")[0],
            note.thought[:60],
            note.metadata.get("tags", ""),
            note.ts.strftime("%Y-%m-%d %H:%M"),
        )
    console.print(table)


@notes_app.command("search")
def notes_search(
    query: str = typer.Argument(help="Search query"),
    limit: int = typer.Option(5, "--limit", "-n", help="Max results"),
) -> None:
    """Search the knowledge base."""
    from hive.memory.semantic import SemanticMemory

    hive_dir = Path.cwd() / ".hive"
    if not hive_dir.exists():
        console.print("[red]Run `hive init` first.[/red]")
        raise typer.Exit(1)

    memory_dir = hive_dir / "memory"
    if not memory_dir.exists():
        console.print("[dim]No notes yet.[/dim]")
        return

    all_results: list[tuple[str, Any]] = []
    for agent_dir in memory_dir.iterdir():
        if agent_dir.is_dir():
            mem = SemanticMemory(hive_dir, agent_dir.name)

            async def _search() -> list[Any]:
                return await mem.search(query, top_k=limit)

            results = asyncio.run(_search())
            all_results.extend((agent_dir.name, r) for r in results)

    if not all_results:
        console.print("[dim]No matching notes.[/dim]")
        return

    table = Table(title=f"Search: {query}")
    table.add_column("ID", style="cyan")
    table.add_column("Agent", style="dim")
    table.add_column("Content")
    table.add_column("Tags", style="dim")

    for agent, note in all_results[:limit]:
        table.add_row(
            note.memory_id,
            agent.split("-")[0],
            note.thought[:80],
            note.metadata.get("tags", ""),
        )
    console.print(table)


@app.command()
def alarms() -> None:
    """List all pending alarms."""
    from hive.memory.store import HiveStore

    hive_dir = Path.cwd() / ".hive"
    if not hive_dir.exists():
        console.print("[red]Run `hive init` first.[/red]")
        raise typer.Exit(1)

    store = HiveStore(hive_dir / "hive.db")
    asyncio.run(store.initialize())
    pending = asyncio.run(store.list_all_pending_alarms())
    if not pending:
        console.print("[dim]No pending alarms.[/dim]")
        return

    table = Table(title="Pending Alarms")
    table.add_column("ID", style="cyan")
    table.add_column("Agent", style="dim")
    table.add_column("Description")
    table.add_column("Fires At", style="yellow")

    for a in pending:
        table.add_row(
            a["alarm_id"],
            a["agent_id"].split("-")[0],
            a["description"][:60],
            a["fire_at"],
        )
    console.print(table)


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host", help="Bind address (local-first default)."),
    port: int = typer.Option(8000, "--port", "-p", help="Port to listen on."),
    with_daemon: bool = typer.Option(
        False, "--with-daemon", help="Run the heartbeat loop in-process."
    ),
    reload: bool = typer.Option(False, "--reload", help="Auto-reload on code changes (dev)."),
) -> None:
    r"""Serve the Hive REST API (requires the 'api' extra: pip install 'hive-agent\[api]')."""
    hive_dir = Path.cwd() / ".hive"
    if not hive_dir.exists():
        console.print("[red]Run `hive init` first.[/red]")
        raise typer.Exit(1)
    try:
        import uvicorn

        from hive.server.app import create_app
    except ImportError as e:
        from hive.errors import MissingDependencyError

        raise MissingDependencyError("api") from e

    console.print(
        f"[green]Hive AgentOS[/green] on http://{host}:{port}  "
        f"(control plane at /, API docs at /docs)"
    )
    app_instance = create_app(root=Path.cwd(), with_daemon=with_daemon)
    uvicorn.run(app_instance, host=host, port=port, reload=reload)


@app.command()
def approvals() -> None:
    """List all pending human-in-the-loop tool approvals."""
    from hive.memory.store import HiveStore

    hive_dir = Path.cwd() / ".hive"
    if not hive_dir.exists():
        console.print("[red]Run `hive init` first.[/red]")
        raise typer.Exit(1)

    store = HiveStore(hive_dir / "hive.db")
    asyncio.run(store.initialize())
    pending = asyncio.run(store.list_all_pending_approvals())
    if not pending:
        console.print("[dim]No pending approvals.[/dim]")
        return

    table = Table(title="Pending Approvals")
    table.add_column("ID", style="cyan")
    table.add_column("Agent", style="dim")
    table.add_column("Tool", style="yellow")
    table.add_column("Arguments", max_width=50)

    for a in pending:
        table.add_row(
            a["approval_id"],
            a["agent_id"].split("-")[0],
            a["tool_name"],
            a["arguments"][:50],
        )
    console.print(table)


def _resolve_approval_cli(approval_id: str, decision: str, reason: str | None) -> None:
    from hive.memory.store import HiveStore

    hive_dir = Path.cwd() / ".hive"
    if not hive_dir.exists():
        console.print("[red]Run `hive init` first.[/red]")
        raise typer.Exit(1)
    store = HiveStore(hive_dir / "hive.db")
    asyncio.run(store.initialize())
    status = "approved" if decision == "approve" else "denied"
    ok = asyncio.run(store.resolve_approval(approval_id, status, resolved_by="cli", reason=reason))
    if not ok:
        console.print(f"[red]Approval {approval_id} is not pending or does not exist.[/red]")
        raise typer.Exit(1)
    verb = "Approved" if decision == "approve" else "Denied"
    console.print(f"[green]✓ {verb}[/green] {approval_id}")


@app.command()
def approve(approval_id: str = typer.Argument(help="Approval ID to approve")) -> None:
    """Approve a pending tool call so the agent can run it next cycle."""
    _resolve_approval_cli(approval_id, "approve", None)


@app.command()
def deny(
    approval_id: str = typer.Argument(help="Approval ID to deny"),
    reason: str = typer.Option("", "--reason", "-r", help="Reason shown to the agent."),
) -> None:
    """Deny a pending tool call. The agent sees the denial and re-plans."""
    _resolve_approval_cli(approval_id, "deny", reason or None)


agent_app = typer.Typer(
    name="agent",
    help="Run individual agents interactively.",
    no_args_is_help=True,
)
app.add_typer(agent_app, name="agent")


@agent_app.command("run")
def agent_run(
    config: Path = typer.Argument(help="Path to agent YAML config file"),
) -> None:
    """Run an agent from a YAML config as an interactive assistant."""
    from hive.serve import serve_from_yaml

    if not config.exists():
        console.print(f"[red]Config file not found: {config}[/red]")
        raise typer.Exit(1)
    serve_from_yaml(config)


@agent_app.command("chat")
def agent_chat(
    model: str = typer.Option("claude-haiku-4-5", "--model", "-m", help="Model to use"),
    no_tools: bool = typer.Option(False, "--no-tools", help="Disable file/shell/git tools"),
    workspace: str = typer.Option(".", "--workspace", "-w", help="Working directory for tools"),
) -> None:
    """Quick-start an interactive agent with tools."""
    from hive.serve import serve_quick

    serve_quick(model=model, tools=not no_tools, workspace=workspace)


if __name__ == "__main__":
    app()
