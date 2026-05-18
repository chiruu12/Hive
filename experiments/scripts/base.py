"""Base experiment runner — shared infrastructure for all experiments."""

import asyncio
import json
import logging
import shutil
import signal
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from rich.console import Console

from hive.agents.state import AgentState, AgentStatus
from hive.checkpoint import CheckpointManager
from hive.config import HiveConfig, get_config, set_config
from hive.daemon.loop import HiveDaemon
from hive.memory.store import HiveStore
from hive.tools.memory import MemoryToolkit
from hive.tools.notepad import NotepadManager, NotepadToolkit

EXPERIMENTS_DIR = Path(__file__).resolve().parent.parent
RESULTS_DIR = EXPERIMENTS_DIR / "results"
REPORTS_DIR = EXPERIMENTS_DIR / "reports"

console = Console()


class Experiment:
    """Base class for Hive experiments.

    Subclass and implement run() to define experiment logic.
    """

    name: str = "unnamed"
    description: str = ""

    def __init__(self) -> None:
        self._tmp_dir: Path | None = None
        self._hive_dir: Path | None = None
        self._results: dict[str, Any] = {}
        self._start_time: datetime | None = None

    @property
    def hive_dir(self) -> Path:
        assert self._hive_dir is not None, "Call setup() first"
        return self._hive_dir

    @property
    def tmp_dir(self) -> Path:
        assert self._tmp_dir is not None, "Call setup() first"
        return self._tmp_dir

    def setup(self) -> None:
        """Create temp .hive/ directory and initialize."""
        self._tmp_dir = Path(tempfile.mkdtemp(prefix=f"hive-exp-{self.name}-"))
        self._hive_dir = self._tmp_dir / ".hive"
        self._hive_dir.mkdir()
        for subdir in (
            "sessions",
            "workspaces",
            "comms",
            "agent_memory",
            "checkpoints",
            "journals",
        ):
            (self._hive_dir / subdir).mkdir()

        cfg = HiveConfig()
        set_config(cfg)
        cfg.save(self._hive_dir)

        store = HiveStore(self._hive_dir / "hive.db")
        asyncio.run(store.initialize())

        self._start_time = datetime.now(UTC)
        console.print(f"\n[bold]{self.name}[/bold] — {self.description}")

    def run(self) -> dict[str, Any]:
        """Override in subclass. Return metrics dict."""
        raise NotImplementedError

    def report(self) -> None:
        """Print Rich summary and save JSON to results/."""
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        filename = f"{self.name}-{ts}.json"
        path = RESULTS_DIR / filename

        output = {
            "experiment": self.name,
            "description": self.description,
            "timestamp": ts,
            "results": self._results,
        }
        path.write_text(json.dumps(output, indent=2, default=str))
        console.print(f"\n[green]Results saved:[/green] {path}")

    def cleanup(self) -> None:
        """Remove temp .hive/ directory."""
        if self._tmp_dir and self._tmp_dir.exists():
            shutil.rmtree(self._tmp_dir, ignore_errors=True)
            console.print("[dim]Temp directory cleaned up.[/dim]")

    def execute(self) -> dict[str, Any]:
        """Full lifecycle: setup -> run -> report -> cleanup."""
        try:
            self.setup()
            self._results = self.run()
            self.report()
            return self._results
        except KeyboardInterrupt:
            console.print("\n[yellow]Experiment interrupted.[/yellow]")
            self.report()
            return self._results
        finally:
            self.cleanup()

    def _spawn_agents(
        self,
        agents: list[dict[str, Any]],
        economy: bool = True,
    ) -> None:
        """Helper: spawn agents into the temp hive store."""
        cfg = get_config()
        cfg.economy.enabled = economy
        set_config(cfg)
        cfg.save(self.hive_dir)

        store = HiveStore(self.hive_dir / "hive.db")
        asyncio.run(store.initialize())

        for agent_cfg in agents:
            name = str(agent_cfg["name"])
            agent_id = f"{name}-exp"
            state = AgentState(
                agent_id=agent_id,
                name=name,
                role=str(agent_cfg.get("role", "general agent")),
                model=str(agent_cfg.get("model", "claude-haiku-4-5")),
                status=AgentStatus.IDLE,
                workspace=str(self.hive_dir / "workspaces" / agent_id),
            )
            asyncio.run(store.save_agent(state))

    def _run_daemon(
        self,
        cycles: int,
        heartbeat: int = 3,
        slim_tools: bool = False,
    ) -> None:
        """Helper: run daemon for N cycles.

        Args:
            slim_tools: If True, replace the daemon's full 50-tool set with
                a minimal set suitable for small local models with limited
                context windows.
        """
        logging.getLogger("hive.tools").setLevel(logging.ERROR)

        daemon = HiveDaemon(
            self.hive_dir,
            heartbeat=heartbeat,
            logs_dir=self.tmp_dir / "logs",
            fresh=True,
        )

        if slim_tools:
            self._apply_slim_tools(daemon)

        self._run_daemon_loop(daemon, cycles, heartbeat)

    def _apply_slim_tools(self, daemon: HiveDaemon) -> None:
        """Replace daemon's full toolkit set with a minimal one."""

        def _slim_build(agent_id: str) -> list[Any]:
            toolkits: list[Any] = [
                MemoryToolkit(path=daemon._ctx.memory_dir),
                NotepadToolkit(manager=daemon._notepad),
            ]
            if daemon._economy_enabled and daemon._ctx.world is not None:
                from hive.tools.world import WorldToolkit

                toolkits.insert(0, WorldToolkit(daemon._ctx.world, agent_id))
            for tk in toolkits:
                tk.bind(agent_id)
            return toolkits

        daemon._build_toolkits = _slim_build  # type: ignore[method-assign]

    def _run_daemon_loop(
        self, daemon: HiveDaemon, cycles: int, heartbeat: int
    ) -> None:
        """Run a daemon for a fixed number of cycles."""

        async def _limited_run() -> None:
            daemon._plugin_toolkits.extend(daemon._plugin_loader.discover())
            while daemon._running and daemon._cycle_count < cycles:
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
                    f"  [dim]cycle {daemon._cycle_count}/{cycles}[/dim]",
                    end="\r",
                )
                await asyncio.sleep(heartbeat)
            daemon._running = False

        daemon._run = _limited_run  # type: ignore[method-assign]

        loop = asyncio.new_event_loop()

        def _stop(signum: int, frame: object) -> None:
            daemon.stop()

        prev_int = signal.signal(signal.SIGINT, _stop)
        prev_term = signal.signal(signal.SIGTERM, _stop)

        try:
            loop.run_until_complete(daemon.start())
        except KeyboardInterrupt:
            pass
        finally:
            loop.close()
            signal.signal(signal.SIGINT, prev_int)
            signal.signal(signal.SIGTERM, prev_term)

    def _collect_agent_metrics(self) -> dict[str, dict[str, Any]]:
        """Helper: collect per-agent metrics from store."""
        store = HiveStore(self.hive_dir / "hive.db")
        agents = asyncio.run(store.list_agents())
        cp_mgr = CheckpointManager(self.hive_dir)
        notepad_mgr = NotepadManager(self.hive_dir)

        metrics: dict[str, dict[str, Any]] = {}
        for agent in agents:
            goals = asyncio.run(store.list_agent_goals(agent.agent_id, limit=500))
            done = sum(1 for g in goals if g["status"] == "completed")
            failed = sum(1 for g in goals if g["status"] == "abandoned")

            cps = cp_mgr.list_checkpoints(agent.agent_id)
            happiness = 0.7
            suffering_load = 0.0
            risk_tolerance = 0.3
            concentration = 1.0
            if cps:
                ps = cps[0].persona_snapshot
                if ps:
                    happiness = ps.get("happiness", 0.7)
                    risk_tolerance = ps.get("risk_tolerance", 0.3)
                    concentration = ps.get("concentration", 1.0)
                ss = cps[0].suffering_snapshot
                if ss:
                    actives = ss.get("active", [])
                    suffering_load = min(
                        1.0,
                        sum(s.get("severity", 0) for s in actives),
                    )

            journal = notepad_mgr.read(agent.agent_id)
            journal_words = len(journal.split()) if journal.strip() else 0

            metrics[agent.agent_id] = {
                "name": agent.name,
                "model": agent.model,
                "goals_completed": done,
                "goals_abandoned": failed,
                "happiness": happiness,
                "suffering_load": suffering_load,
                "risk_tolerance": risk_tolerance,
                "concentration": concentration,
                "journal_word_count": journal_words,
                "journal_text": journal,
            }

        return metrics
