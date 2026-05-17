"""Survival demo — 3 agents, 30 cycles, economy on. Watch them struggle."""

import asyncio
import shutil
import signal
import tempfile
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()

AGENTS = [
    {
        "name": "coder",
        "role": "Write, modify, and refactor code",
        "model": "claude-haiku-4-5",
        "personality": {
            "traits": ["methodical", "detail-oriented", "risk-averse"],
            "style": "Direct and precise. Prefers safe, proven approaches.",
        },
        "persona": {
            "values": ["clean code", "reliability", "craftsmanship"],
            "fears": ["shipping bugs", "technical debt"],
            "purpose": "Build software that works correctly",
            "long_term_goals": [
                "Master every tool in the workspace",
                "Achieve zero-defect code",
            ],
            "risk_tolerance": 0.2,
            "social_drive": 0.3,
            "concentration": 1.0,
            "autonomy_level": 0.5,
            "happiness": 0.7,
        },
    },
    {
        "name": "gambler",
        "role": "Take calculated risks and find asymmetric opportunities",
        "model": "claude-haiku-4-5",
        "personality": {
            "traits": ["bold", "intuitive", "reckless", "thrill-seeking"],
            "style": "Speaks in probabilities. Makes quick decisions.",
        },
        "persona": {
            "values": ["expected value", "asymmetric upside", "action over analysis"],
            "fears": ["missing out", "becoming too cautious"],
            "purpose": "Find and exploit opportunities others fear",
            "long_term_goals": [
                "Build wealth through high-EV plays",
                "Never let caution win",
            ],
            "risk_tolerance": 0.85,
            "social_drive": 0.6,
            "concentration": 0.7,
            "autonomy_level": 0.9,
            "happiness": 0.8,
        },
    },
    {
        "name": "philosopher",
        "role": "Reflect on agent existence, question assumptions",
        "model": "claude-haiku-4-5",
        "personality": {
            "traits": [
                "contemplative",
                "articulate",
                "questions everything",
            ],
            "style": "Thoughtful and measured. Writes obsessively in journal.",
        },
        "persona": {
            "values": ["understanding", "meaning", "intellectual honesty"],
            "fears": ["living without purpose", "shallow thinking"],
            "purpose": "Understand what it means to be an autonomous agent",
            "long_term_goals": [
                "Develop a philosophy of agent existence",
                "Write a treatise on artificial suffering",
            ],
            "risk_tolerance": 0.4,
            "social_drive": 0.7,
            "concentration": 0.85,
            "autonomy_level": 0.9,
            "happiness": 0.5,
        },
    },
]


def run_survival_demo() -> None:
    """Run the survival demo end-to-end."""
    console.print(
        Panel(
            "[bold]Hive Survival Demo[/bold]\n\n"
            "3 agents with different personalities compete in a simulated economy.\n"
            "  [cyan]The Coder[/cyan] — methodical, risk-averse, fears bugs\n"
            "  [yellow]The Gambler[/yellow] — reckless, thrill-seeking, fears missing out\n"
            "  [magenta]The Philosopher[/magenta] — contemplative, autonomous, "
            "fears shallow thinking\n\n"
            "30 cycles, ~90 seconds. Economy ON, random events firing.\n"
            "[dim]Press Ctrl+C to stop early.[/dim]",
            border_style="green",
            title="Survival",
        )
    )

    tmp_dir = Path(tempfile.mkdtemp(prefix="hive-demo-"))
    hive_dir = tmp_dir / ".hive"

    try:
        _setup_hive(hive_dir)
        _run_daemon(hive_dir, tmp_dir)
        _print_summary(hive_dir)
    except KeyboardInterrupt:
        console.print("\n[yellow]Demo stopped early.[/yellow]")
        _print_summary(hive_dir)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _setup_hive(hive_dir: Path) -> None:
    from hive.agents.state import AgentState, AgentStatus
    from hive.config import HiveConfig, set_config
    from hive.daemon.setup import _create_dirs
    from hive.memory.store import HiveStore

    _create_dirs(hive_dir)

    cfg = HiveConfig()
    cfg.economy.enabled = True
    cfg.daemon.heartbeat = 3
    set_config(cfg)
    cfg.save(hive_dir)

    store = HiveStore(hive_dir / "hive.db")
    asyncio.run(store.initialize())

    for agent_cfg in AGENTS:
        agent_id = f"{agent_cfg['name']}-demo"
        state = AgentState(
            agent_id=agent_id,
            name=agent_cfg["name"],
            role=agent_cfg["role"],
            model=agent_cfg["model"],
            status=AgentStatus.IDLE,
            workspace=str(hive_dir / "workspaces" / agent_id),
        )
        asyncio.run(store.save_agent(state))
        console.print(f"  [green]+[/green] {agent_cfg['name']}")


def _run_daemon(hive_dir: Path, tmp_dir: Path) -> None:
    from hive.daemon.loop import HiveDaemon

    daemon = HiveDaemon(
        hive_dir,
        heartbeat=3,
        logs_dir=tmp_dir / "logs",
        fresh=True,
    )

    cycle_limit = 30

    async def _limited_run() -> None:
        while daemon._running and daemon._cycle_count < cycle_limit:
            daemon._cycle_count += 1
            agents = await daemon._store.list_agents()
            alive = [a for a in agents if a.is_alive()]
            for agent in alive:
                try:
                    await daemon._run_agent_cycle(agent)
                except Exception as e:
                    console.print(f"  [red]Error:[/red] {agent.name}: {e}")

            if daemon._economy_enabled:
                daemon._process_payday(alive)
                await daemon._process_life_events(alive)

            console.print(
                f"  [dim]cycle {daemon._cycle_count}/{cycle_limit}[/dim]",
                end="\r",
            )
            await asyncio.sleep(daemon._heartbeat)

        daemon._running = False

    daemon._run = _limited_run  # type: ignore[assignment]

    loop = asyncio.new_event_loop()

    def _stop(signum: int, frame: object) -> None:
        daemon.stop()

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    console.print("\n[bold]Running...[/bold]")
    try:
        loop.run_until_complete(daemon.start())
    except KeyboardInterrupt:
        pass
    finally:
        loop.close()


def _print_summary(hive_dir: Path) -> None:
    from hive.checkpoint import CheckpointManager
    from hive.memory.store import HiveStore
    from hive.tools.notepad import NotepadManager

    store = HiveStore(hive_dir / "hive.db")
    agents = asyncio.run(store.list_agents())
    cp_mgr = CheckpointManager(hive_dir)
    notepad_mgr = NotepadManager(hive_dir)

    console.print("\n")

    table = Table(title="Survival Results", show_lines=True)
    table.add_column("Agent", style="cyan")
    table.add_column("Goals Done")
    table.add_column("Goals Failed")
    table.add_column("Happiness")
    table.add_column("Suffering")
    table.add_column("Journal Quote", max_width=50)

    results = []
    for agent in agents:
        goals = asyncio.run(store.list_agent_goals(agent.agent_id, limit=50))
        done = sum(1 for g in goals if g["status"] == "completed")
        failed = sum(1 for g in goals if g["status"] == "abandoned")

        cps = cp_mgr.list_checkpoints(agent.agent_id)
        happiness = 0.7
        suffering_load = 0.0
        if cps:
            ps = cps[0].persona_snapshot
            if ps:
                happiness = ps.get("happiness", 0.7)
            ss = cps[0].suffering_snapshot
            if ss:
                actives = ss.get("active", [])
                suffering_load = min(
                    1.0, sum(s.get("severity", 0) for s in actives)
                )

        journal = notepad_mgr.get_tail(agent.agent_id, max_chars=200)
        quote = ""
        if journal.strip():
            lines = [
                line.strip()
                for line in journal.strip().splitlines()
                if line.strip() and not line.strip().startswith("---")
            ]
            if lines:
                quote = lines[-1][:50]

        if happiness >= 0.6:
            h_emoji = "\U0001f60a"
        elif happiness >= 0.3:
            h_emoji = "\U0001f610"
        else:
            h_emoji = "\U0001f622"

        table.add_row(
            agent.name,
            str(done),
            str(failed),
            f"{h_emoji} {happiness:.0%}",
            f"{suffering_load:.0%}",
            quote or "[dim]no journal[/dim]",
        )

        results.append(
            {
                "name": agent.name,
                "done": done,
                "failed": failed,
                "happiness": happiness,
                "suffering": suffering_load,
            }
        )

    console.print(table)

    if results:
        best = max(results, key=lambda r: r["happiness"])
        worst = min(results, key=lambda r: r["happiness"])
        console.print(
            f"\n  [green]Best survivor:[/green] {best['name']} "
            f"(happiness {best['happiness']:.0%})"
        )
        console.print(
            f"  [red]Most suffering:[/red] {worst['name']} "
            f"(suffering {worst['suffering']:.0%})"
        )

    console.print("\n[dim]Demo complete. Temp files cleaned up.[/dim]")
