"""Action hierarchy — unified model for all agent decisions."""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel

from hive.execution.context import ExecutionContext

logger = logging.getLogger(__name__)


class ActionResult(BaseModel):
    success: bool
    output: str
    action_type: str
    action_name: str
    artifacts: list[str] = []


class Action(BaseModel, ABC):
    """Base for all agent actions. Subclasses define specific behavior."""

    type: str
    rationale: str = ""

    @abstractmethod
    async def execute(self, ctx: ExecutionContext, agent_id: str) -> ActionResult: ...


class ToolAction(Action):
    """Execute a registered tool via the tool registry."""

    type: Literal["tool"] = "tool"
    tool_name: str = ""
    params: dict[str, Any] = {}

    async def execute(self, ctx: ExecutionContext, agent_id: str) -> ActionResult:
        from hive.execution.registry import get_registry

        registry = get_registry()
        result = await registry.execute(self.tool_name, agent_id, **self.params)
        return ActionResult(
            success=result.success,
            output=result.output,
            action_type="tool",
            action_name=self.tool_name,
            artifacts=result.artifacts,
        )


class WorldAction(Action):
    """Execute a world-state action (work, learn, gamble, apply_job, quit_job)."""

    type: Literal["world"] = "world"
    action: str = ""
    target: str = ""
    amount: str = ""

    @staticmethod
    def _result(success: bool, output: str, name: str) -> ActionResult:
        return ActionResult(
            success=success,
            output=output,
            action_type="world",
            action_name=name,
        )

    async def execute(self, ctx: ExecutionContext, agent_id: str) -> ActionResult:
        w = ctx.world

        if self.action == "work":
            out = w.work(agent_id)
            return self._result("Earned" in out, out, "work")

        if self.action == "apply_job":
            out = w.apply_job(agent_id, self.target)
            return self._result("Hired" in out, out, "apply_job")

        if self.action == "quit_job":
            out = w.quit_job(agent_id)
            return self._result("Quit" in out, out, "quit_job")

        if self.action == "learn":
            out = w.learn(agent_id, self.target)
            return self._result("Studied" in out, out, "learn")

        if self.action == "gamble":
            wager = float(self.amount) if self.amount else 10.0
            result = w.gamble(agent_id, self.target or "blackjack", wager)
            return ActionResult(
                success=True, output=result.description, action_type="world", action_name="gamble"
            )

        return ActionResult(
            success=False,
            output=f"Unknown world action: {self.action}",
            action_type="world",
            action_name=self.action,
        )


class MessageAction(Action):
    """Send a message to another agent."""

    type: Literal["message"] = "message"
    target_agent: str = ""
    message: str = ""

    async def execute(self, ctx: ExecutionContext, agent_id: str) -> ActionResult:
        if not self.target_agent or not self.message:
            return ActionResult(
                success=False,
                output="Missing target or message",
                action_type="message",
                action_name="send",
            )
        inbox = ctx.comms_dir / f"{self.target_agent}_inbox.jsonl"
        entry = json.dumps(
            {
                "from": agent_id,
                "message": self.message,
                "ts": datetime.now(UTC).isoformat(),
            }
        )
        with open(inbox, "a") as f:
            f.write(entry + "\n")
        return ActionResult(
            success=True,
            output=f"Sent to {self.target_agent}",
            action_type="message",
            action_name="send",
        )


class MemoryAction(Action):
    """Read or write agent-scoped memory."""

    type: Literal["memory"] = "memory"
    operation: str = "get"
    key: str = ""
    value: str = ""

    async def execute(self, ctx: ExecutionContext, agent_id: str) -> ActionResult:
        path = ctx.memory_dir / f"{agent_id}.json"
        if not path.exists():
            path.write_text("{}")
        data = json.loads(path.read_text())

        if self.operation == "set":
            data[self.key] = self.value
            path.write_text(json.dumps(data, indent=2))
            return ActionResult(
                success=True,
                output=f"Stored: {self.key}",
                action_type="memory",
                action_name="set",
            )

        value = data.get(self.key)
        if value is None:
            return ActionResult(
                success=False,
                output=f"Key not found: {self.key}",
                action_type="memory",
                action_name="get",
            )
        return ActionResult(
            success=True,
            output=str(value),
            action_type="memory",
            action_name="get",
        )


ACTION_TYPES = {
    "tool": ToolAction,
    "world": WorldAction,
    "message": MessageAction,
    "memory": MemoryAction,
}


def parse_action(data: dict) -> Action | None:
    """Parse a dict into a typed Action. Returns None on failure."""
    action_type = data.get("type", "tool")
    cls = ACTION_TYPES.get(action_type)
    if not cls:
        logger.warning("Unknown action type: %s", action_type)
        return None
    try:
        return cls(**data)
    except Exception as e:
        logger.warning("Failed to parse action: %s", e)
        return None


def parse_action_plan(text: str) -> list[Action]:
    """Parse Claude's JSON response into a list of Action objects."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])
    try:
        steps = json.loads(text)
        if not isinstance(steps, list):
            return []
    except json.JSONDecodeError:
        logger.warning("Failed to parse action plan JSON: %s", text[:200])
        return []

    actions = []
    for step in steps:
        if not isinstance(step, dict):
            continue
        if "type" not in step:
            if "tool_name" in step or "tool" in step:
                step["type"] = "tool"
                step.setdefault("tool_name", step.pop("tool", ""))
            elif "action" in step:
                step["type"] = "world"
        action = parse_action(step)
        if action:
            actions.append(action)
    return actions
