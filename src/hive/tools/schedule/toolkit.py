"""Schedule toolkit for recurring agent goals."""

from __future__ import annotations

from typing import TYPE_CHECKING

from hive.tools.base import Toolkit, tool

if TYPE_CHECKING:
    from hive.memory.store import HiveStore


class ScheduleToolkit(Toolkit):
    """Tools for scheduling recurring goals.

    Usage:
        tk = ScheduleToolkit(store=my_store)   # daemon provides store
        # agent_id set via bind()
    """

    def __init__(self, store: HiveStore, agent_id: str = ""):
        self._store = store
        self._agent_id = agent_id

    @tool()
    async def schedule_goal(self, objective: str, every_n_cycles: int) -> str:
        """Schedule a recurring goal that fires every N cycles.

        Args:
            objective: What to accomplish each time.
            every_n_cycles: How often (in daemon cycles) to fire.
        """
        from uuid import uuid4

        if every_n_cycles < 1:
            return "Cycle interval must be at least 1."
        sid = f"sched-{uuid4().hex[:8]}"
        await self._store.save_schedule(sid, self._agent_id, objective, every_n_cycles)
        return f"Scheduled '{objective}' every {every_n_cycles} cycles (id={sid})."

    @tool()
    async def list_schedules(self) -> str:
        """List all your active scheduled goals."""
        schedules = await self._store.list_schedules(self._agent_id)
        if not schedules:
            return "No scheduled goals."
        lines = []
        for s in schedules:
            lines.append(
                f'- {s["schedule_id"]}: "{s["objective"]}" '
                f"every {s['every_n_cycles']} cycles "
                f"(last fired: cycle {s['last_fired_cycle']})"
            )
        return "\n".join(lines)

    @tool()
    async def cancel_schedule(self, schedule_id: str) -> str:
        """Cancel a scheduled goal.

        Args:
            schedule_id: The schedule ID to cancel.
        """
        await self._store.disable_schedule(schedule_id)
        return f"Schedule {schedule_id} cancelled."
