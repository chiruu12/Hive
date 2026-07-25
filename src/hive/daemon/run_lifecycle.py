"""Daemon run lifecycle — start, resume, shutdown, and alarm polling."""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from hive.agents.state import AgentStatus
from hive.agents.suffering import SufferingState
from hive.config import get_config
from hive.daemon.agent_context import AgentContextCache
from hive.tools.alarms import fire_notification

if TYPE_CHECKING:
    from hive.daemon.loop import HiveDaemon

logger = logging.getLogger(__name__)


class DaemonAlreadyRunningError(RuntimeError):
    """Raised when ``start()`` finds a live PID in the daemon lockfile."""

    def __init__(self, pid: int, lockfile: Path) -> None:
        self.pid = pid
        self.lockfile = lockfile
        super().__init__(
            f"Another daemon is already running (PID {pid}). Stop it first or delete {lockfile}"
        )


def check_no_live_daemon(hive_dir: Path) -> None:
    """Raise :class:`DaemonAlreadyRunningError` if a live PID owns the lockfile."""
    lockfile = hive_dir / "daemon.pid"
    if not lockfile.exists():
        return
    try:
        old_pid = int(lockfile.read_text().strip())
        os.kill(old_pid, 0)
        raise DaemonAlreadyRunningError(old_pid, lockfile)
    except (ValueError, ProcessLookupError, PermissionError):
        lockfile.unlink(missing_ok=True)


class RunLifecycle:
    """PID lock, agent resume, alarm task, and shutdown checkpoints."""

    def __init__(self, daemon: HiveDaemon, context: AgentContextCache) -> None:
        self._d = daemon
        self._ctx = context

    async def start(self, max_cycles: int | None = None) -> None:
        """Initialize store, start heartbeat.

        Args:
            max_cycles: Stop after this many cycles. ``None`` runs until stopped.
        """
        lockfile = self._d._hive_dir / "daemon.pid"
        if lockfile.exists():
            try:
                old_pid = int(lockfile.read_text().strip())
                # Check if the old process is still alive
                os.kill(old_pid, 0)
                raise DaemonAlreadyRunningError(old_pid, lockfile)
            except DaemonAlreadyRunningError:
                raise
            except (ValueError, ProcessLookupError, PermissionError):
                # Old process is dead or PID is invalid — safe to proceed
                lockfile.unlink(missing_ok=True)

        # Atomic PID file write: write to a temp file in the same directory
        # then rename (atomic on POSIX). Prevents two daemons starting
        # simultaneously from both passing the liveness check and writing.
        fd, tmp_path = tempfile.mkstemp(dir=str(self._d._hive_dir), suffix=".pid.tmp")
        try:
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            fd = -1  # Mark as closed
            os.rename(tmp_path, str(lockfile))
        except BaseException:
            if fd >= 0:
                os.close(fd)
            Path(tmp_path).unlink(missing_ok=True)
            raise

        await self._d._store.initialize()

        if not self._d._fresh:
            await self.resume_agents()

        agents = await self._d._store.list_agents()
        agent_ids = [a.agent_id for a in agents if a.is_alive()]
        tool_names = self._d._get_tool_names()
        cfg = get_config()
        self._d._log.start_run(
            heartbeat=self._d._heartbeat,
            profiles=self._d._profiles,
            agents=agent_ids,
            tools=tool_names,
            seed=self._d._seed,
            economy_enabled=self._d._economy_enabled,
            model={
                "default_model": cfg.model.default_model,
                "planning_model": cfg.model.planning_model,
                "temperature": cfg.model.temperature,
                "max_tokens": cfg.model.max_tokens,
            },
        )

        logger.info(
            "Daemon started: run=%s, %d tools, heartbeat=%ds, economy=%s",
            self._d._log.run_id,
            len(tool_names),
            self._d._heartbeat,
            self._d._economy_enabled,
        )
        self._d._running = True
        self._d._stop_event = asyncio.Event()
        self._d._alarm_task = asyncio.create_task(self.alarm_check_loop())
        try:
            await self._d._run(max_cycles)
        finally:
            # Always shut down -- including on exceptions escaping _run and on
            # task cancellation -- so shutdown checkpoints are written and the
            # alarm task is never orphaned.
            self._d._running = False
            await self.shutdown()

    async def alarm_check_loop(self) -> None:
        """Poll for due alarms every 15 seconds and fire notifications."""
        while self._d._running:
            try:
                due = await self._d._store.get_due_alarms()
                for alarm in due:
                    ok = await fire_notification(alarm["description"])
                    if not ok:
                        logger.warning(
                            "Alarm %s notification failed, marking fired anyway",
                            alarm["alarm_id"],
                        )
                    await self._d._store.mark_alarm_fired(alarm["alarm_id"])
            except Exception as e:
                logger.warning("Alarm check failed: %s", e)
            await asyncio.sleep(15)

    async def resume_agents(self) -> None:
        """Resume agents from a previous run, restoring suffering from checkpoints."""
        try:
            existing = await self._d._store.list_agents()
        except Exception:
            return
        resumable = [a for a in existing if a.status != AgentStatus.DEAD]
        if not resumable:
            return
        logger.info("Resuming %d agents from previous run", len(resumable))
        for agent in resumable:
            # Keep a parked agent parked across the restart: an agent that is WAITING
            # with a still-pending approval should retain WAITING + its active goal, so
            # the park gate holds it next heartbeat instead of resetting to IDLE and
            # burning a full LLM cycle before re-parking. (The cycle counter resets on
            # restart, but the pending approval row persists.)
            parked = bool(
                get_config().approval.enabled
                and agent.status == AgentStatus.WAITING
                and await self._d._store.get_pending_approvals(agent.agent_id)
            )
            # An operator-paused agent stays paused across restarts.
            if not parked and agent.status != AgentStatus.PAUSED:
                await self._d._store.update_agent_status(agent.agent_id, AgentStatus.IDLE)
            cps = self._d._checkpoint.list_checkpoints(agent.agent_id)
            if cps:
                snap = cps[0].suffering_snapshot
                try:
                    restored = SufferingState.model_validate(snap)
                    self._d._suffering[agent.agent_id] = restored
                    logger.info(
                        "Restored checkpoint for %s (load=%.0f%%)",
                        agent.agent_id,
                        restored.cumulative_load * 100,
                    )
                except Exception:
                    # Corrupt/incompatible snapshot: start this agent from a clean
                    # suffering state rather than silently leaving it unset.
                    self._d._suffering[agent.agent_id] = SufferingState(agent_id=agent.agent_id)
                    logger.warning(
                        "Could not restore suffering for %s; using a fresh state",
                        agent.agent_id,
                        exc_info=True,
                    )
                persona_snap = cps[0].persona_snapshot
                if persona_snap:
                    profile = self._ctx.load_profile(agent.name)
                    persona = self._ctx.get_persona(agent.agent_id, profile)
                    if persona is not None:
                        try:
                            persona.restore_dynamic(persona_snap)
                        except Exception:
                            logger.warning(
                                "Could not restore persona for %s; "
                                "keeping the freshly built persona",
                                agent.agent_id,
                                exc_info=True,
                            )
            if not parked:
                active = await self._d._store.get_active_goal(agent.agent_id)
                if active:
                    if get_config().daemon.preserve_active_goals_on_restart:
                        logger.info(
                            "resumed_active_goal goal_id=%s agent_id=%s",
                            active["goal_id"],
                            agent.agent_id,
                        )
                    else:
                        await self._d._store.abandon_goal(active["goal_id"])
                        logger.info(
                            "Abandoned stale goal %s for %s",
                            active["goal_id"],
                            agent.agent_id,
                        )

    async def shutdown(self) -> None:
        """Checkpoint all agents, flush budget, then release the PID lockfile."""
        lockfile = self._d._hive_dir / "daemon.pid"

        try:
            alarm_task = self._d._alarm_task
            if alarm_task is not None and not alarm_task.done():
                alarm_task.cancel()
                try:
                    await alarm_task
                except asyncio.CancelledError:
                    pass

            logger.info("shutdown_phase=checkpoint")
            try:
                agents = await self._d._store.list_agents()
                for agent in agents:
                    if not agent.is_alive():
                        continue
                    suffering = self._ctx.get_suffering(agent.agent_id)
                    identity = self._d._identity.load(agent.agent_id)
                    persona = self._d._personas.get(agent.agent_id)
                    goals = await self._d._store.list_agent_goals(agent.agent_id, limit=10)
                    self._d._checkpoint.save(
                        agent.agent_id,
                        "daemon_shutdown",
                        suffering,
                        identity,
                        self._d._ctx,
                        goals,
                        persona_snapshot=persona.snapshot() if persona else None,
                    )
                    active = await self._d._store.get_active_goal(agent.agent_id)
                    if active and not get_config().daemon.preserve_active_goals_on_restart:
                        await self._d._store.abandon_goal(active["goal_id"])
                    logger.info("Checkpointed %s on shutdown", agent.agent_id)
            except Exception as e:
                logger.warning("Checkpoint on shutdown failed: %s", e)

            logger.info("shutdown_phase=budget")
            self._d.persist_budget()

            # Defensive narrowing rather than asserts: this is the shutdown path, and
            # a crash here would lose life summaries (asserts also vanish under -O).
            if (
                self._d._economy_enabled
                and self._d._life_writer is not None
                and self._d._stats is not None
                and self._d._ctx.world is not None
                and self._d._event_engine is not None
            ):
                try:
                    agents = await self._d._store.list_agents()
                except Exception:
                    logger.warning(
                        "Could not list agents for life summaries on shutdown",
                        exc_info=True,
                    )
                else:
                    for agent in agents:
                        if not agent.is_alive():
                            continue
                        try:
                            summary = self._d._life_writer.generate(
                                agent.agent_id,
                                self._d._identity,
                                self._d._stats,
                                self._d._ctx.world,
                                self._d._event_engine,
                                self._d._store,
                                self._d._cycle_count,
                            )
                            path = self._d._life_writer.write(summary)
                            logger.info("Life summary written: %s", path)
                        except Exception as e:
                            logger.warning(
                                "Failed to write life summary for %s: %s",
                                agent.agent_id,
                                e,
                            )

            # Clean up old run logs
            try:
                retention = get_config().retention
                if retention.max_runs > 0:
                    deleted = self._d._log.cleanup_old_runs(retention.max_runs)
                    if deleted:
                        logger.info("Cleaned up %d old run logs", deleted)
            except Exception:
                logger.warning("Failed to clean up old run logs", exc_info=True)
        finally:
            logger.info("shutdown_phase=pid_release")
            lockfile.unlink(missing_ok=True)
