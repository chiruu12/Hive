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


def _server_base_url() -> str:
    """Base URL of the local `hive serve` instance (default port 8000)."""
    import os

    return os.environ.get("HIVE_SERVER_URL", "http://127.0.0.1:8000")


def _server_headers() -> dict[str, str]:
    """Auth headers for the local REST server, if an API key is configured."""
    import os

    key = os.environ.get("HIVE_API_KEY", "")
    if not key:
        cfg_path = Path.cwd() / ".hive" / "config.yaml"
        if cfg_path.exists():
            import yaml

            try:
                data = yaml.safe_load(cfg_path.read_text()) or {}
                key = (data.get("server") or {}).get("api_key", "") or ""
            except Exception:
                key = ""
    return {"X-Hive-Key": key} if key else {}


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
    from hive.agents.profile import AgentProfile, resolve_profiles_dir
    from hive.agents.state import AgentState, AgentStatus
    from hive.config import HiveConfig, load_config, resolve_logs_dir
    from hive.daemon.loop import HiveDaemon
    from hive.daemon.run_lifecycle import DaemonAlreadyRunningError
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

    profiles_dir = resolve_profiles_dir(hive_dir)
    profile_names = [p.strip() for p in profiles.split(",")]

    cfg = HiveConfig.load(hive_dir)
    if cfg.daemon.heartbeat != heartbeat:
        cfg.daemon.heartbeat = heartbeat
        cfg.save(hive_dir)
    load_config(hive_dir)

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
        logs_dir=resolve_logs_dir(hive_dir),
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
    except DaemonAlreadyRunningError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from e
    except KeyboardInterrupt:
        pass
    finally:
        loop.close()
        console.print("[dim]Hive stopped.[/dim]")


@app.command()
def stop(
    timeout: int = typer.Option(
        30, "--timeout", "-t", help="Seconds to wait for graceful shutdown"
    ),
) -> None:
    """Stop a running daemon from another terminal."""
    import os
    import time

    hive_dir = Path.cwd() / ".hive"
    pid_file = hive_dir / "daemon.pid"

    if not pid_file.exists():
        console.print("[yellow]No daemon.pid found. Daemon may not be running.[/yellow]")
        raise typer.Exit(1)

    try:
        pid = int(pid_file.read_text().strip())
    except ValueError:
        console.print("[red]Invalid daemon.pid file.[/red]")
        pid_file.unlink(missing_ok=True)
        raise typer.Exit(1)

    # Check if process is alive
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        console.print("[yellow]Daemon process not found. Cleaning up stale pidfile.[/yellow]")
        pid_file.unlink(missing_ok=True)
        raise typer.Exit(0)
    except PermissionError:
        console.print(f"[red]No permission to signal PID {pid}.[/red]")
        raise typer.Exit(1)

    console.print(f"Sending SIGTERM to daemon (PID {pid})...")
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        console.print("[yellow]Process already exited.[/yellow]")
        pid_file.unlink(missing_ok=True)
        raise typer.Exit(0)

    # Wait for graceful shutdown
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            console.print("[green]Daemon stopped.[/green]")
            pid_file.unlink(missing_ok=True)
            raise typer.Exit(0)
        time.sleep(0.5)

    console.print(f"[red]Daemon did not exit within {timeout}s. Sending SIGKILL...[/red]")
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    pid_file.unlink(missing_ok=True)
    console.print("[yellow]Daemon killed.[/yellow]")


@app.command()
def restart(
    heartbeat: int = typer.Option(10, "--heartbeat", "-b", help="Seconds between cycles"),
    profiles: str = typer.Option("coder", "--profiles", "-p", help="Comma-separated profiles"),
    fresh: bool = typer.Option(False, "--fresh", help="Ignore saved state"),
    timeout: int = typer.Option(15, "--timeout", "-t", help="Seconds to wait for stop"),
) -> None:
    """Stop a running daemon and start a new one."""
    import os
    import time as _time

    hive_dir = Path.cwd() / ".hive"
    pid_file = hive_dir / "daemon.pid"

    # Stop existing daemon if running
    if pid_file.exists():
        try:
            pid = int(pid_file.read_text().strip())
            os.kill(pid, 0)
            console.print(f"[yellow]Stopping daemon (PID {pid})...[/yellow]")
            os.kill(pid, signal.SIGTERM)
            deadline = _time.monotonic() + timeout
            while _time.monotonic() < deadline:
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    break
                _time.sleep(0.5)
            else:
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            pid_file.unlink(missing_ok=True)
            console.print("[green]Daemon stopped.[/green]")
        except (ValueError, ProcessLookupError, PermissionError):
            pid_file.unlink(missing_ok=True)

    # Start new daemon
    start(heartbeat=heartbeat, profiles=profiles, fresh=fresh)


daemon_app = typer.Typer(
    name="daemon",
    help="Daemon control: status, freeze, resume.",
    invoke_without_command=True,
)
app.add_typer(daemon_app, name="daemon")


@daemon_app.callback()
def daemon_status(ctx: typer.Context) -> None:
    """Show daemon health: PID, uptime, cycles, budget, agents."""
    if ctx.invoked_subcommand is not None:
        return
    import os

    import httpx

    hive_dir = Path.cwd() / ".hive"
    pid_file = hive_dir / "daemon.pid"

    # Check PID file
    pid = None
    pid_alive = False
    if pid_file.exists():
        try:
            pid = int(pid_file.read_text().strip())
            os.kill(pid, 0)
            pid_alive = True
        except (ValueError, ProcessLookupError, PermissionError):
            pass

    if not pid_alive:
        console.print(
            Panel(
                "[bold red]Daemon not running[/bold red]\n\n"
                f"  PID file: {'exists (stale)' if pid_file.exists() else 'not found'}\n"
                f"  PID: {pid or 'n/a'}\n\n"
                "[dim]Start with: hive start[/dim]",
                title="Daemon Status",
                border_style="red",
            )
        )
        raise typer.Exit(1)

    # Gather info
    lines = [
        f"[bold]PID:[/bold]  {pid}",
        "[bold]Status:[/bold]  [green]running[/green]",
    ]

    pause_file = hive_dir / "daemon.paused"
    if pause_file.exists():
        lines.append("[bold]Daemon freeze:[/bold]  [yellow]PAUSED[/yellow]")

    # Try to get process uptime
    try:
        import subprocess

        result = subprocess.run(
            ["ps", "-o", "etime=", "-p", str(pid)],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            lines.append(f"[bold]Uptime:[/bold]  {result.stdout.strip()}")
    except Exception:
        pass

    # Query server for richer info
    try:
        resp = httpx.get(f"{_server_base_url()}/status", headers=_server_headers(), timeout=3)
        if resp.status_code == 200:
            agents = resp.json()
            working = sum(1 for a in agents if a.get("status") == "working")
            idle = sum(1 for a in agents if a.get("status") == "idle")
            waiting = sum(1 for a in agents if a.get("status") == "waiting_approval")
            paused = sum(1 for a in agents if a.get("status") == "paused")
            lines.append(
                f"[bold]Agents:[/bold]  {len(agents)} total"
                f" ({working} working, {idle} idle, {waiting} waiting, {paused} paused)"
            )
    except Exception:
        lines.append("[bold]Agents:[/bold]  [dim]server not reachable[/dim]")

    try:
        resp = httpx.get(f"{_server_base_url()}/budget", headers=_server_headers(), timeout=3)
        if resp.status_code == 200:
            b = resp.json()
            budget_str = f"${b['spent_usd']:.4f}"
            if b.get("unlimited") or not b["budget_usd"]:
                budget_str += " [yellow](unlimited — budget_usd=0)[/yellow]"
            else:
                budget_str += f" / ${b['budget_usd']:.2f}"
            exceeded = " [red]EXCEEDED[/red]" if b["exceeded"] else ""
            lines.append(f"[bold]Budget:[/bold]  {budget_str}{exceeded}")
        elif hive_dir.exists():
            from hive.daemon.budget import budget_snapshot_to_dict, read_budget_snapshot

            snap = budget_snapshot_to_dict(read_budget_snapshot(hive_dir))
            budget_str = f"${snap['spent_usd']:.4f}"
            if snap.get("unlimited") or not snap["budget_usd"]:
                budget_str += " [yellow](unlimited — budget_usd=0)[/yellow]"
            else:
                budget_str += f" / ${snap['budget_usd']:.2f}"
            exceeded = " [red]EXCEEDED[/red]" if snap["exceeded"] else ""
            lines.append(
                f"[bold]Budget:[/bold]  {budget_str}{exceeded} [dim](ledger fallback)[/dim]"
            )
    except Exception:
        if hive_dir.exists():
            try:
                from hive.daemon.budget import budget_snapshot_to_dict, read_budget_snapshot

                snap = budget_snapshot_to_dict(read_budget_snapshot(hive_dir))
                budget_str = f"${snap['spent_usd']:.4f}"
                if snap.get("unlimited") or not snap["budget_usd"]:
                    budget_str += " [yellow](unlimited — budget_usd=0)[/yellow]"
                else:
                    budget_str += f" / ${snap['budget_usd']:.2f}"
                exceeded = " [red]EXCEEDED[/red]" if snap["exceeded"] else ""
                lines.append(
                    f"[bold]Budget:[/bold]  {budget_str}{exceeded} [dim](ledger fallback)[/dim]"
                )
            except Exception:
                pass

    console.print(
        Panel(
            "\n".join(lines),
            title="Daemon Status",
            border_style="green",
        )
    )


@daemon_app.command("pause")
def daemon_pause() -> None:
    """Freeze the whole daemon (ManualPauseGuard). Distinct from ``hive pause <agent>``."""
    import httpx

    hive_dir = Path.cwd() / ".hive"
    if not hive_dir.exists():
        console.print("[red]Run `hive init` first.[/red]")
        raise typer.Exit(1)

    pause_file = hive_dir / "daemon.paused"
    pause_file.write_text("1\n")

    try:
        resp = httpx.post(
            f"{_server_base_url()}/daemon/pause",
            headers=_server_headers(),
            timeout=5,
        )
        if resp.status_code == 200:
            console.print("[yellow]Daemon frozen[/yellow] (in-process guard + pause file).")
            return
        if resp.status_code == 503:
            console.print(
                "[yellow]Daemon freeze set[/yellow] via `.hive/daemon.paused` "
                "(standalone `hive start` picks this up on the next heartbeat)."
            )
            return
        console.print(f"[red]Server returned {resp.status_code}[/red]")
    except httpx.ConnectError:
        console.print(
            "[yellow]Daemon freeze set[/yellow] via `.hive/daemon.paused` "
            "(no REST server; running daemon syncs on next heartbeat)."
        )


@daemon_app.command("resume")
def daemon_resume() -> None:
    """Clear the daemon-wide freeze (``ManualPauseGuard``)."""
    import httpx

    hive_dir = Path.cwd() / ".hive"
    if not hive_dir.exists():
        console.print("[red]Run `hive init` first.[/red]")
        raise typer.Exit(1)

    pause_file = hive_dir / "daemon.paused"
    pause_file.unlink(missing_ok=True)

    try:
        resp = httpx.post(
            f"{_server_base_url()}/daemon/resume",
            headers=_server_headers(),
            timeout=5,
        )
        if resp.status_code == 200:
            console.print("[green]Daemon resumed[/green].")
            return
        if resp.status_code == 503:
            console.print(
                "[green]Pause file cleared[/green] "
                "(standalone `hive start` resumes on the next heartbeat)."
            )
            return
        console.print(f"[red]Server returned {resp.status_code}[/red]")
    except httpx.ConnectError:
        console.print(
            "[green]Pause file cleared[/green] "
            "(no REST server; running daemon syncs on next heartbeat)."
        )


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
        "paused": "[blue]paused[/blue]",
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
    from hive.agents.profile import AgentProfile, resolve_profiles_dir
    from hive.agents.state import AgentState, AgentStatus
    from hive.memory.store import HiveStore

    hive_dir = Path.cwd() / ".hive"
    if not hive_dir.exists():
        console.print("[red]Run `hive init` first.[/red]")
        raise typer.Exit(1)

    profiles_dir = resolve_profiles_dir(hive_dir)
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
def edit(
    agent: str = typer.Argument(help="Agent name or ID"),
    model: str = typer.Option("", "--model", "-m", help="New model name"),
    role: str = typer.Option("", "--role", "-r", help="New role description"),
) -> None:
    """Edit an agent's model or role after spawn."""
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

    changes = []
    if model:
        target.model = model
        changes.append(f"model → {model}")
    if role:
        target.role = role
        changes.append(f"role → {role}")

    if not changes:
        console.print("[yellow]No changes specified. Use --model or --role.[/yellow]")
        raise typer.Exit(1)

    asyncio.run(store.save_agent(target))
    console.print(f"[green]✓[/green] Updated {target.name}: {', '.join(changes)}")


@app.command()
def pause(
    agent: str = typer.Argument("", help="Agent name or ID (omit for --all)"),
    all_agents: bool = typer.Option(False, "--all", "-a", help="Pause all agents"),
) -> None:
    """Pause one or all agents (per-agent status in SQLite).

    For a daemon-wide freeze that blocks all cycles, use ``hive daemon pause``.
    """
    from hive.agents.state import AgentStatus
    from hive.memory.store import HiveStore

    hive_dir = Path.cwd() / ".hive"
    if not hive_dir.exists():
        console.print("[red]Run `hive init` first.[/red]")
        raise typer.Exit(1)

    store = HiveStore(hive_dir / "hive.db")

    if all_agents:
        agents = asyncio.run(store.list_agents())
        count = 0
        for a in agents:
            if a.status not in (AgentStatus.DEAD, AgentStatus.PAUSED):
                asyncio.run(store.update_agent_status(a.agent_id, AgentStatus.PAUSED))
                count += 1
        console.print(f"[yellow]Paused {count} agents.[/yellow]")
        return

    if not agent:
        console.print("[red]Specify an agent or use --all.[/red]")
        raise typer.Exit(1)

    agents = asyncio.run(store.list_agents())
    target = None
    for a in agents:
        if a.agent_id == agent or a.name == agent or a.agent_id.startswith(agent):
            target = a
            break
    if not target:
        console.print(f"[red]Agent not found: {agent}[/red]")
        raise typer.Exit(1)

    asyncio.run(store.update_agent_status(target.agent_id, AgentStatus.PAUSED))
    console.print(f"[yellow]Paused[/yellow] {target.name}")


@app.command()
def resume(
    agent: str = typer.Argument("", help="Agent name or ID (omit for --all)"),
    all_agents: bool = typer.Option(False, "--all", "-a", help="Resume all agents"),
) -> None:
    """Resume a paused agent or all agents."""
    from hive.agents.state import AgentStatus
    from hive.memory.store import HiveStore

    hive_dir = Path.cwd() / ".hive"
    if not hive_dir.exists():
        console.print("[red]Run `hive init` first.[/red]")
        raise typer.Exit(1)

    store = HiveStore(hive_dir / "hive.db")

    if all_agents:
        agents = asyncio.run(store.list_agents())
        count = 0
        for a in agents:
            if a.status == AgentStatus.PAUSED:
                asyncio.run(store.update_agent_status(a.agent_id, AgentStatus.IDLE))
                count += 1
        console.print(f"[green]Resumed {count} agents.[/green]")
        return

    if not agent:
        console.print("[red]Specify an agent or use --all.[/red]")
        raise typer.Exit(1)

    agents = asyncio.run(store.list_agents())
    target = None
    for a in agents:
        if a.agent_id == agent or a.name == agent or a.agent_id.startswith(agent):
            target = a
            break
    if not target:
        console.print(f"[red]Agent not found: {agent}[/red]")
        raise typer.Exit(1)

    if target.status != AgentStatus.PAUSED:
        console.print(f"[yellow]{target.name} is {target.status.value}, not paused.[/yellow]")
        raise typer.Exit(1)

    asyncio.run(store.update_agent_status(target.agent_id, AgentStatus.IDLE))
    console.print(f"[green]Resumed[/green] {target.name}")


@app.command()
def history(
    agent: str = typer.Argument(help="Agent name or ID"),
    limit: int = typer.Option(20, "--limit", "-n", help="Number of entries"),
) -> None:
    """Show an agent's goal history."""
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

    goals = asyncio.run(store.list_agent_goals(target.agent_id, limit=limit))
    if not goals:
        console.print(f"[dim]No goal history for {target.name}.[/dim]")
        return

    table = Table(title=f"History: {target.name} ({target.agent_id})")
    table.add_column("Goal ID", style="dim")
    table.add_column("Status", style="bold")
    table.add_column("Objective", max_width=60)

    status_icons = {
        "completed": "[green]✓[/green]",
        "abandoned": "[red]✗[/red]",
        "in_progress": "[yellow]⟳[/yellow]",
        "pending": "[dim]·[/dim]",
    }

    for g in goals:
        icon = status_icons.get(g.get("status", ""), "?")
        obj = (g.get("objective", "") or "")[:80]
        table.add_row(g.get("goal_id", "?"), icon, obj)

    console.print(table)


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
    from hive.daemon.wakeup import touch_nudge_wake_file

    touch_nudge_wake_file(hive_dir, nudge_id)
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
            "paused": "[blue]paused[/blue]",
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
def config(
    key: str = typer.Argument("", help="Config key to show/set (e.g. daemon.heartbeat)"),
    value: str = typer.Argument("", help="Value to set (omit to show current)"),
    validate_only: bool = typer.Option(False, "--validate", help="Validate config only"),
    effective: bool = typer.Option(False, "--effective", help="Show effective config (disk + env)"),
    persisted: bool = typer.Option(False, "--persisted", help="Show persisted YAML only"),
    live: bool = typer.Option(False, "--live", help="Show in-process live config cache"),
) -> None:
    """View, set, or validate Hive configuration.

    Examples:
        hive config                          # Show persisted config
        hive config --effective              # Disk + env overrides
        hive config --live                   # In-process cache (when daemon ran)
        hive config daemon.heartbeat         # Show a specific key
        hive config daemon.heartbeat 30      # Set a value
        hive config --validate               # Validate config
    """
    import yaml

    from hive.config import (
        apply_config_patch,
        config_truth_views,
        load_config,
    )

    hive_dir = Path.cwd() / ".hive"
    if not hive_dir.exists():
        console.print("[red]No .hive directory. Run `hive init` first.[/red]")
        raise typer.Exit(1)

    config_path = hive_dir / "config.yaml"

    if validate_only:
        try:
            from hive.config import load_config

            cfg = load_config(hive_dir)
            console.print("[green]Config is valid.[/green]")
            if (
                cfg.daemon.warn_unlimited_budget
                and cfg.daemon.budget_usd <= 0
                and cfg.daemon.budget_tokens <= 0
            ):
                console.print(
                    "[yellow]Warning: daemon budget is unlimited "
                    "(budget_usd=0 and budget_tokens=0). "
                    "Set non-zero limits for production kill-switch.[/yellow]"
                )
        except Exception as e:
            console.print(f"[red]Config error: {e}[/red]")
            raise typer.Exit(1)
        return

    if effective or persisted or live:
        views = config_truth_views(hive_dir)
        if effective:
            payload = views["effective"]
            title = "Effective Configuration (disk + env)"
        elif persisted:
            payload = views["persisted"]
            title = "Persisted Configuration (YAML only)"
        else:
            payload = views["live"]
            title = "Live Configuration (in-process cache)"
            if payload is None:
                console.print(
                    "[yellow]No live config cache in this process. "
                    "Use --effective for disk+env values.[/yellow]"
                )
                raise typer.Exit(0)
        console.print(
            Panel(
                yaml.dump(payload, default_flow_style=False).strip(),
                title=title,
                border_style="blue",
            )
        )
        restart_fields = views["restart_required_fields"]
        if restart_fields:
            console.print(
                "[dim]Restart-required prefixes: "
                + ", ".join(restart_fields[:8])
                + ("..." if len(restart_fields) > 8 else "")
                + "[/dim]"
            )
        return

    # Load current config
    data: dict[str, Any] = {}
    if config_path.exists():
        with open(config_path) as f:
            data = yaml.safe_load(f) or {}

    if not key:
        # Show all config
        console.print(
            Panel(
                yaml.dump(data, default_flow_style=False).strip(),
                title="Hive Configuration",
                border_style="blue",
            )
        )
        return

    # Navigate to the key
    parts = key.split(".")
    if not value:
        # Show specific key
        current = data
        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                console.print(f"[red]Key not found: {key}[/red]")
                raise typer.Exit(1)
        console.print(f"[bold]{key}[/bold]: {current}")
        return

    # Set value via shared patch helper (same logic as REST PATCH /config)
    patch: dict[str, Any] = {}
    current_patch = patch
    for part in parts[:-1]:
        current_patch[part] = {}
        current_patch = current_patch[part]

    cast_value: Any = value
    if value.lower() in ("true", "false"):
        cast_value = value.lower() == "true"
    elif value.isdigit():
        cast_value = int(value)
    else:
        try:
            cast_value = float(value)
        except ValueError:
            pass

    current_patch[parts[-1]] = cast_value

    try:
        _, reload_status = apply_config_patch(hive_dir, patch)
        load_config(hive_dir)
    except Exception as e:
        console.print(f"[red]Invalid config: {e}[/red]")
        raise typer.Exit(1)

    console.print(f"[green]Set {key} = {cast_value}[/green]")
    restart_keys = [k for k, status in reload_status.items() if status == "restart_required"]
    if restart_keys:
        console.print(
            "[yellow]Restart required for: "
            + ", ".join(restart_keys)
            + " — run `hive restart`.[/yellow]"
        )
    applied_keys = [k for k, status in reload_status.items() if status == "applied"]
    if applied_keys:
        console.print(
            "[dim]Hot-reload on next daemon heartbeat: " + ", ".join(applied_keys) + "[/dim]"
        )


@app.command()
def profiles(
    name: str = typer.Argument("", help="Profile name to inspect"),
) -> None:
    """List available agent profiles or inspect one."""
    from hive.agents.profile import resolve_profiles_dir

    hive_dir = Path.cwd() / ".hive"
    profiles_dir = resolve_profiles_dir(hive_dir if hive_dir.exists() else None)
    if not profiles_dir.exists():
        console.print("[yellow]No profiles directory found.[/yellow]")
        raise typer.Exit(1)

    if name:
        # Show specific profile (name only -- reject path separators)
        if "/" in name or "\\" in name or name.startswith("."):
            console.print(f"[red]Invalid profile name: {name}[/red]")
            raise typer.Exit(1)
        profile_path = profiles_dir / f"{name}.yaml"
        if not profile_path.exists():
            console.print(f"[red]Profile not found: {name}[/red]")
            raise typer.Exit(1)
        console.print(
            Panel(
                profile_path.read_text(),
                title=f"Profile: {name}",
                border_style="blue",
            )
        )
        return

    # List all profiles
    yaml_files = sorted(profiles_dir.glob("*.yaml"))
    if not yaml_files:
        console.print("[yellow]No profiles found.[/yellow]")
        return

    table = Table(title="Available Profiles")
    table.add_column("Name", style="cyan")
    table.add_column("Role", style="white")
    table.add_column("Model", style="dim")

    for p in yaml_files:
        import yaml as _yaml

        data = _yaml.safe_load(p.read_text()) or {}
        table.add_row(
            p.stem,
            data.get("role", "—"),
            data.get("model", "—"),
        )
    console.print(table)


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
    from hive.config import resolve_logs_dir
    from hive.logging.reader import LogReader

    hive_dir = Path.cwd() / ".hive"
    logs_dir = resolve_logs_dir(hive_dir if hive_dir.exists() else Path.cwd() / ".hive")
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
    from hive.config import resolve_logs_dir
    from hive.logging.reader import LogReader

    hive_dir = Path.cwd() / ".hive"
    logs_dir = resolve_logs_dir(hive_dir if hive_dir.exists() else Path.cwd() / ".hive")
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
def trace(
    run_id: str = typer.Argument(help="Run ID to trace"),
    full: bool = typer.Option(False, "--full", "-f", help="Show all attributes"),
) -> None:
    """Display the span-tree trace for a run."""
    from hive.config import resolve_logs_dir
    from hive.logging.reader import LogReader
    from hive.logging.trace import TraceBuilder, format_span_tree

    hive_dir = Path.cwd() / ".hive"
    logs_dir = resolve_logs_dir(hive_dir if hive_dir.exists() else Path.cwd() / ".hive")
    reader = LogReader(logs_dir)
    builder = TraceBuilder(reader)
    tree = builder.build(run_id)

    if tree is None:
        console.print(f"[red]Run not found: {run_id}[/red]")
        raise typer.Exit(1)

    console.print(
        Panel(
            f"[bold]Run:[/bold] {tree.run_id}\n  Total spans: {tree.total_spans}",
            title="Trace",
            border_style="blue",
        )
    )
    console.print()
    console.print(format_span_tree(tree.root))


@app.command()
def new(
    name: str = typer.Argument(help="Project name"),
    template: str = typer.Option(
        "minimal", "--template", "-t", help="Template: minimal, team, research"
    ),
    force: bool = typer.Option(False, "--force", "-f", help="Overwrite existing .hive directory"),
) -> None:
    """Scaffold a new Hive project directory."""
    from hive.cli.templates import scaffold_project, validate_project_name

    err = validate_project_name(name)
    if err:
        console.print(f"[red]{err}[/red]")
        raise typer.Exit(1)

    try:
        hive_dir = scaffold_project(name, template, Path.cwd(), force=force)
        profiles = list((Path.cwd() / "profiles").glob("*.yaml"))
        console.print(
            Panel(
                f"[bold]Project:[/bold] {name}\n"
                f"  Template: {template}\n"
                f"  Directory: {hive_dir}\n"
                f"  Agents: {len(profiles)} profile(s)\n\n"
                f"[dim]Next steps:[/dim]\n"
                f"  hive status    # Check agents\n"
                f"  hive start     # Start daemon",
                title="hive new",
                border_style="green",
            )
        )
    except FileExistsError as e:
        console.print(f"[red]{e}[/red]")
        console.print("[dim]Use --force to overwrite.[/dim]")
        raise typer.Exit(1)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)


@app.command()
def demo(
    name: str = typer.Argument("", help="Demo name (omit to list available demos)"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Suppress output"),
) -> None:
    """Run an interactive demo. Omit name to see available demos."""
    from hive.demos.registry import list_demos, run_demo

    demos = list_demos()

    if not name:
        console.print(Panel("[bold]Available Demos[/bold]", border_style="blue"))
        for dname, desc in demos.items():
            console.print(f"  [cyan]{dname}[/cyan]: {desc}")
        console.print("\n[dim]Usage: hive demo <name>[/dim]")
        return

    if name not in demos:
        console.print(f"[red]Unknown demo: {name}[/red]")
        console.print(f"Available: {', '.join(sorted(demos))}")
        raise typer.Exit(1)

    try:
        result = run_demo(name, quiet=quiet)
        console.print(
            Panel(
                f"[bold]Demo:[/bold] {result.name}\n"
                f"  Agents: {', '.join(result.agents) if result.agents else 'n/a'}\n"
                f"  Cycles: {result.cycles}\n"
                f"  {result.summary}",
                title="Demo Complete",
                border_style="green",
            )
        )
    except Exception as e:
        console.print(f"[red]Demo failed: {e}[/red]")
        raise typer.Exit(1)


budget_app = typer.Typer(help="Daemon cost budget status and controls.")
app.add_typer(budget_app, name="budget")


def _render_budget_panel(data: dict[str, Any], *, source: str = "") -> None:
    unlimited = data.get("unlimited") or not data["budget_usd"]
    if unlimited and not data["budget_tokens"]:
        budget_usd = "[yellow]unlimited (budget_usd=0)[/yellow]"
        budget_tok = "[yellow]unlimited (budget_tokens=0)[/yellow]"
    else:
        budget_usd = data["budget_usd"] or "unlimited"
        budget_tok = data["budget_tokens"] or "unlimited"
    spent_usd = f"${data['spent_usd']:.4f}"
    spent_tok = f"{data['spent_tokens']:,}"
    remaining_usd = f"${data['remaining_usd']:.4f}" if data["remaining_usd"] is not None else "n/a"
    remaining_tok = (
        f"{data['remaining_tokens']:,}" if data["remaining_tokens"] is not None else "n/a"
    )
    reserved_usd = f"${data.get('reserved_usd', 0.0):.4f}"
    reserved_tok = f"{data.get('reserved_tokens', 0):,}"
    exceeded = "[red]YES[/red]" if data["exceeded"] else "[green]no[/green]"
    mode = data.get("mode", "reserve")
    title = "Budget" + (f" ({source})" if source else "")
    console.print(
        Panel(
            f"[bold]USD:[/bold]  {spent_usd} / {budget_usd}"
            f"  (remaining: {remaining_usd}, reserved: {reserved_usd})\n"
            f"[bold]Tokens:[/bold]  {spent_tok} / {budget_tok}"
            f"  (remaining: {remaining_tok}, reserved: {reserved_tok})\n"
            f"[bold]Mode:[/bold]  {mode}\n"
            f"[bold]Exceeded:[/bold]  {exceeded}",
            title=title,
            border_style="yellow",
        )
    )


@budget_app.callback(invoke_without_command=True)
def budget_status(ctx: typer.Context) -> None:
    """Show daemon-level cost budget status."""
    if ctx.invoked_subcommand is not None:
        return

    import httpx

    from hive.daemon.budget import budget_snapshot_to_dict, read_budget_snapshot

    hive_dir = Path.cwd() / ".hive"
    try:
        resp = httpx.get(f"{_server_base_url()}/budget", headers=_server_headers(), timeout=5)
        if resp.status_code == 200:
            _render_budget_panel(resp.json(), source="REST")
            return
    except httpx.ConnectError:
        pass
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        return

    if not hive_dir.exists():
        console.print(
            "[yellow]REST server not reachable and no .hive directory. "
            "Run `hive init` first.[/yellow]"
        )
        return

    summary = read_budget_snapshot(hive_dir)
    _render_budget_panel(budget_snapshot_to_dict(summary), source="standalone ledger")
    console.print(
        "[dim]Read-only snapshot from .hive/budget.json + config limits. "
        "Running daemon may differ until next persist.[/dim]"
    )


@budget_app.command("reset")
def budget_reset() -> None:
    """Reset daemon budget spent counters."""

    import httpx

    from hive.daemon.budget import reset_budget_ledger

    hive_dir = Path.cwd() / ".hive"
    try:
        resp = httpx.post(
            f"{_server_base_url()}/budget/reset",
            headers=_server_headers(),
            timeout=5,
        )
        if resp.status_code == 200:
            console.print("[green]Budget counters reset (REST).[/green]")
            return
    except httpx.ConnectError:
        pass
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        return

    if not hive_dir.exists():
        console.print(
            "[yellow]REST server not reachable and no .hive directory. "
            "Run `hive init` first.[/yellow]"
        )
        return

    reset_budget_ledger(hive_dir)
    console.print(
        "[green]Budget ledger reset (.hive/budget.json).[/green]\n"
        "[dim]If a standalone daemon is running, restart it to reload in-memory counters.[/dim]"
    )


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
    from hive.config import resolve_logs_dir
    from hive.export.html import export_html_report

    hive_dir = Path.cwd() / ".hive"
    logs_dir = resolve_logs_dir(hive_dir if hive_dir.exists() else Path.cwd() / ".hive")
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
        raise typer.Exit(1)
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

        from hive.config import load_config
        from hive.server.app import create_app
        from hive.server.security import validate_serve_bind
    except ImportError as e:
        from hive.errors import MissingDependencyError

        raise MissingDependencyError("api") from e

    hive_config = load_config(hive_dir)
    try:
        validate_serve_bind(host, hive_config)
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc

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
