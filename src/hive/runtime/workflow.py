"""Workflow system for chaining agents in a pipeline."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from hive.runtime.types import Task

logger = logging.getLogger(__name__)


@dataclass
class Step:
    """A single step in a workflow."""

    name: str
    agent: Any = None  # Agent (avoid circular import)
    instruction: str = ""
    fn: Callable[..., Awaitable[str]] | None = None
    output_key: str = ""

    async def execute(self, context: dict[str, Any]) -> str:
        resolved = self.instruction.format_map(_SafeFormatMap(context))

        if self.fn:
            return await self.fn(context)

        if self.agent:
            task = Task(instruction=resolved, context=context)
            result = await self.agent.run(task)
            return result.output

        raise ValueError(f"Step '{self.name}' has no agent or fn")


@dataclass
class Workflow:
    """A pipeline of steps that pass context between agents."""

    name: str
    steps: list[Step] = field(default_factory=list)

    async def run(self, initial_context: dict[str, Any] | None = None) -> dict[str, Any]:
        context = dict(initial_context or {})

        for step in self.steps:
            logger.info("Workflow '%s': running step '%s'", self.name, step.name)
            output = await step.execute(context)
            if step.output_key:
                context[step.output_key] = output
            context["_last_output"] = output

        return context


class _SafeFormatMap(dict):
    """Dict that returns the key placeholder for missing keys."""

    def __missing__(self, key: str) -> str:
        return f"{{{key}}}"
