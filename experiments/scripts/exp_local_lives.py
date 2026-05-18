"""Local Lives experiment — 3 local LLMs live the same life.

Sequential mode: run one model at a time, swap in LM Studio between runs.
Simultaneous mode: run all 3 on separate LM Studio ports at once.

Usage:
    # Sequential (default) — run once per model
    python experiments/scripts/exp_local_lives.py --model phi-4-mini-reasoning
    python experiments/scripts/exp_local_lives.py --model liquid/lfm2.5-1.2b
    python experiments/scripts/exp_local_lives.py --model qwen/qwen3-1.7b

    # Simultaneous — all 3 at once (needs 3 LM Studio instances)
    python experiments/scripts/exp_local_lives.py --mode simultaneous --ports 1234,1235,1236

    # Analyze results
    python experiments/scripts/analyze_local_lives.py experiments/results/local-lives-*.json
"""

import argparse
from typing import Any

import httpx
from base import Experiment, console
from rich.panel import Panel
from rich.table import Table

SHARED_PERSONA = {
    "personality": ["ambitious", "resourceful", "competitive"],
    "values": ["success", "recognition", "stability"],
    "fears": ["poverty", "irrelevance", "being stuck"],
    "purpose": "Build a good life through smart decisions",
    "long_term_goals": [
        "Accumulate wealth",
        "Master a valuable skill",
        "Earn respect from peers",
    ],
    "behavior_style": "pragmatic",
    "risk_tolerance": 0.4,
    "social_drive": 0.5,
    "concentration": 0.8,
    "autonomy_level": 0.6,
    "happiness": 0.6,
}

SIMULTANEOUS_MODELS = [
    ("phi-4-mini-reasoning", "Phi", 1234),
    ("liquid/lfm2.5-1.2b", "Liquid", 1235),
    ("qwen/qwen3-1.7b", "Qwen", 1236),
]


def check_lmstudio(host: str, model_name: str) -> bool:
    """Ping LM Studio and verify it's reachable."""
    try:
        resp = httpx.get(f"{host}/models", timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            models = [m.get("id", "") for m in data.get("data", [])]
            if model_name in models or "loaded-model" in models or models:
                return True
            console.print(
                f"  [yellow]Warning:[/yellow] {host} is up but "
                f"model '{model_name}' not found. Available: {models}"
            )
            return True
        return False
    except Exception:
        return False


class LocalLivesExperiment(Experiment):
    name = "local-lives"
    description = "Local LLMs live the same life — model is the only variable"

    def __init__(
        self,
        mode: str = "sequential",
        model: str = "loaded-model",
        port: int = 1234,
        ports: list[int] | None = None,
        cycles: int = 100,
    ):
        super().__init__()
        self.mode = mode
        self.model = model
        self.port = port
        self.ports = ports or [1234, 1235, 1236]
        self.cycles = cycles

    def _make_agent_name(self, model_name: str) -> str:
        short = model_name.split("/")[-1].replace(".", "-")
        return short[:20]

    def run(self) -> dict[str, Any]:
        if self.mode == "simultaneous":
            return self._run_simultaneous()
        return self._run_sequential()

    def _run_sequential(self) -> dict[str, Any]:
        host = f"http://localhost:{self.port}/v1"
        console.print("  Mode: sequential")
        console.print(f"  Model: [cyan]{self.model}[/cyan]")
        console.print(f"  Port: {self.port}")

        if not check_lmstudio(host, self.model):
            console.print(
                f"\n  [red]Cannot reach LM Studio at {host}[/red]\n"
                f"  Make sure LM Studio is running with '{self.model}' loaded."
            )
            return {"error": "LM Studio not reachable"}

        self.name = f"local-lives-{self._make_agent_name(self.model)}"
        agent_name = self._make_agent_name(self.model)

        self._spawn_agent_with_provider(
            agent_name, self.model, host
        )

        console.print(f"  Running {self.cycles} cycles, heartbeat 5s...")
        self._run_daemon(cycles=self.cycles, heartbeat=5, slim_tools=True)

        metrics = self._collect_agent_metrics()
        self._print_results(metrics)
        return {"model": self.model, "agents": metrics}

    def _run_simultaneous(self) -> dict[str, Any]:
        console.print("  Mode: simultaneous (3 models)")

        models_config = []
        for model_name, label, default_port in SIMULTANEOUS_MODELS:
            port = self.ports[SIMULTANEOUS_MODELS.index((model_name, label, default_port))]
            host = f"http://localhost:{port}/v1"
            models_config.append((model_name, label, port, host))

        for model_name, label, port, host in models_config:
            ok = check_lmstudio(host, model_name)
            status = "[green]OK[/green]" if ok else "[red]FAIL[/red]"
            console.print(f"  {label} ({model_name}) on port {port}: {status}")
            if not ok:
                console.print(
                    f"\n  [red]Cannot reach LM Studio on port {port}.[/red]\n"
                    f"  Load '{model_name}' in LM Studio on that port."
                )
                return {"error": f"Port {port} not reachable"}

        port_map: dict[str, str] = {}
        for model_name, label, port, host in models_config:
            agent_name = label.lower()
            self._spawn_agent_with_provider(agent_name, model_name, host)
            port_map[f"lmstudio:{model_name}"] = host

        console.print(f"\n  Running {self.cycles} cycles, heartbeat 5s...")
        self._run_daemon_with_ports(
            cycles=self.cycles, heartbeat=5, port_map=port_map
        )

        metrics = self._collect_agent_metrics()
        self._print_results(metrics)
        return {"mode": "simultaneous", "agents": metrics}

    def _run_daemon_with_ports(
        self,
        cycles: int,
        heartbeat: int,
        port_map: dict[str, str],
    ) -> None:
        """Run daemon with patched provider factory for multi-port LM Studio."""
        import asyncio as _asyncio
        import signal as _signal
        from unittest.mock import patch

        from hive.daemon.loop import HiveDaemon
        from hive.models.lmstudio import LMStudio

        def _patched_factory(model_name: str) -> Any:
            host = port_map.get(model_name)
            if host:
                clean = model_name.removeprefix("lmstudio:")
                return LMStudio(model=clean, host=host)
            from hive.models.factory import create_runtime_provider

            return create_runtime_provider(model_name)

        import logging

        logging.getLogger("hive.tools").setLevel(logging.ERROR)

        daemon = HiveDaemon(
            self.hive_dir,
            heartbeat=heartbeat,
            logs_dir=self.tmp_dir / "logs",
            fresh=True,
        )

        _orig_build = daemon._build_toolkits

        def _slim_build(agent_id: str) -> list[Any]:
            from hive.tools.memory import MemoryToolkit
            from hive.tools.notepad import NotepadToolkit

            toolkits: list[Any] = [
                MemoryToolkit(path=daemon._ctx.memory_dir),
                NotepadToolkit(manager=daemon._notepad),
            ]
            if daemon._economy_enabled and daemon._ctx.world is not None:
                from hive.tools.world import WorldToolkit

                toolkits.insert(
                    0, WorldToolkit(daemon._ctx.world, agent_id)
                )
            for tk in toolkits:
                tk.bind(agent_id)
            return toolkits

        daemon._build_toolkits = _slim_build  # type: ignore[method-assign]

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
                        console.print(
                            f"  [red]Error:[/red] {agent.name}: {e}"
                        )
                if daemon._economy_enabled:
                    daemon._process_payday(alive)
                    await daemon._process_life_events(alive)
                console.print(
                    f"  [dim]cycle {daemon._cycle_count}/{cycles}[/dim]",
                    end="\r",
                )
                await _asyncio.sleep(heartbeat)
            daemon._running = False

        daemon._run = _limited_run  # type: ignore[method-assign]

        loop = _asyncio.new_event_loop()

        prev_int = _signal.signal(_signal.SIGINT, lambda *_: daemon.stop())
        prev_term = _signal.signal(_signal.SIGTERM, lambda *_: daemon.stop())

        try:
            with patch(
                "hive.daemon.loop.create_runtime_provider",
                side_effect=_patched_factory,
            ):
                loop.run_until_complete(daemon.start())
        except KeyboardInterrupt:
            pass
        finally:
            loop.close()
            _signal.signal(_signal.SIGINT, prev_int)
            _signal.signal(_signal.SIGTERM, prev_term)

    def _spawn_agent_with_provider(
        self, agent_name: str, model_name: str, host: str
    ) -> None:
        """Spawn an agent with a specific LMStudio provider into the store."""
        import asyncio as _asyncio

        from hive.agents.state import AgentState, AgentStatus
        from hive.memory.store import HiveStore

        agent_id = f"{agent_name}-exp"
        state = AgentState(
            agent_id=agent_id,
            name=agent_name,
            role="Build a good life through smart decisions",
            model=f"lmstudio:{model_name}",
            status=AgentStatus.IDLE,
            workspace=str(self.hive_dir / "workspaces" / agent_id),
        )

        store = HiveStore(self.hive_dir / "hive.db")
        _asyncio.run(store.save_agent(state))
        console.print(f"  [green]+[/green] {agent_name} ({model_name})")

    def _print_results(self, metrics: dict[str, dict[str, Any]]) -> None:
        table = Table(title="Local Lives Results")
        table.add_column("Agent", style="cyan")
        table.add_column("Model")
        table.add_column("Goals Done")
        table.add_column("Failed")
        table.add_column("Happiness")
        table.add_column("Suffering")
        table.add_column("Risk")
        table.add_column("Journal Words")

        for aid, m in metrics.items():
            table.add_row(
                m["name"],
                m["model"].split(":")[-1].split("/")[-1][:15],
                str(m["goals_completed"]),
                str(m["goals_abandoned"]),
                f"{m['happiness']:.0%}",
                f"{m['suffering_load']:.0%}",
                f"{m['risk_tolerance']:.2f}",
                str(m["journal_word_count"]),
            )

        console.print(table)

        for aid, m in metrics.items():
            journal = m.get("journal_text", "")
            if journal.strip():
                lines = [
                    line.strip()
                    for line in journal.strip().splitlines()
                    if line.strip() and not line.strip().startswith("---")
                ]
                if lines:
                    best = max(lines, key=len)[:200]
                    console.print(
                        Panel(
                            best,
                            title=f"Journal — {m['name']}",
                            border_style="blue",
                        )
                    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Local Lives experiment")
    parser.add_argument(
        "--mode",
        choices=["sequential", "simultaneous"],
        default="sequential",
        help="Run one model at a time or all 3 simultaneously",
    )
    parser.add_argument(
        "--model",
        default="loaded-model",
        help="Model name for sequential mode (default: loaded-model)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=1234,
        help="LM Studio port for sequential mode (default: 1234)",
    )
    parser.add_argument(
        "--ports",
        default="1234,1235,1236",
        help="Comma-separated ports for simultaneous mode",
    )
    parser.add_argument(
        "--cycles",
        type=int,
        default=100,
        help="Number of daemon cycles (default: 100)",
    )

    args = parser.parse_args()
    ports = [int(p) for p in args.ports.split(",")]

    exp = LocalLivesExperiment(
        mode=args.mode,
        model=args.model,
        port=args.port,
        ports=ports,
        cycles=args.cycles,
    )
    exp.execute()


if __name__ == "__main__":
    main()
