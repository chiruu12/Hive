"""Agent with ReAct loop — the core of the Hive runtime."""

from __future__ import annotations

import logging
import time

from hive.runtime.memory import ConversationMemory, PersistentMemory
from hive.runtime.providers import RuntimeProvider
from hive.runtime.tools import Tool, Toolkit
from hive.runtime.types import Message, Task, TaskResult, TaskStatus

logger = logging.getLogger(__name__)


class Agent:
    """An autonomous agent with tools, memory, and a ReAct loop.

    The ReAct loop:
    1. Send conversation to the model with available tools
    2. If the model returns tool_calls, execute them and feed results back
    3. If the model returns text only, the task is done
    4. Repeat until done or max_steps exceeded
    """

    def __init__(
        self,
        name: str,
        model: RuntimeProvider,
        system_prompt: str = "",
        toolkits: list[Toolkit] | None = None,
        tools: list[Tool] | None = None,
        memory: PersistentMemory | None = None,
        max_steps: int = 25,
        temperature: float = 0.0,
    ):
        self.name = name
        self._model = model
        self._system_prompt = system_prompt
        self._toolkits = toolkits or []
        self._extra_tools = tools or []
        self._memory = memory
        self._max_steps = max_steps
        self._temperature = temperature

    def _collect_tools(self) -> list[Tool]:
        all_tools: list[Tool] = list(self._extra_tools)
        for tk in self._toolkits:
            all_tools.extend(tk.get_tools())
        return all_tools

    async def run(self, task: Task) -> TaskResult:
        """Execute a task using the ReAct loop."""
        t0 = time.time()

        tools = self._collect_tools()
        tool_map = {t.name: t for t in tools}
        tool_schemas = [t.to_schema() for t in tools] if tools else None

        max_steps = task.max_steps or self._max_steps

        conversation = ConversationMemory(
            system_prompt=self._system_prompt,
            max_messages=max_steps * 4,
        )

        if self._memory:
            try:
                relevant = await self._memory.recall(task.instruction, limit=3)
                if relevant:
                    context_lines = [
                        f"- {m.get('thought', m.get('content', str(m)))}"
                        for m in relevant
                    ]
                    conversation.add(
                        Message.system(
                            "Relevant memories:\n" + "\n".join(context_lines)
                        )
                    )
            except Exception:
                logger.debug("Failed to recall persistent memory", exc_info=True)

        if task.context:
            context_str = "\n".join(f"{k}: {v}" for k, v in task.context.items())
            conversation.add(
                Message.user(f"{task.instruction}\n\nContext:\n{context_str}")
            )
        else:
            conversation.add(Message.user(task.instruction))

        steps = 0
        tool_calls_total = 0

        while steps < max_steps:
            steps += 1

            try:
                response = await self._model.generate(
                    messages=conversation.get_messages(),
                    tools=tool_schemas,
                    temperature=self._temperature,
                )
            except Exception as e:
                logger.error("Model generation failed: %s", e)
                return TaskResult(
                    task_id=task.id,
                    status=TaskStatus.FAILED,
                    output="",
                    error=str(e),
                    steps_taken=steps,
                    tool_calls_made=tool_calls_total,
                    duration_seconds=time.time() - t0,
                )

            conversation.add(response)

            if not response.tool_calls:
                return TaskResult(
                    task_id=task.id,
                    status=TaskStatus.COMPLETED,
                    output=response.content,
                    steps_taken=steps,
                    tool_calls_made=tool_calls_total,
                    duration_seconds=time.time() - t0,
                )

            for tc in response.tool_calls:
                tool_calls_total += 1
                tool = tool_map.get(tc.name)

                if tool is None:
                    available = ", ".join(tool_map.keys())
                    conversation.add(
                        Message.tool_result(
                            tc.id,
                            f"Error: unknown tool '{tc.name}'. Available: {available}",
                            is_error=True,
                            name=tc.name,
                        )
                    )
                    continue

                try:
                    result_text = await tool.call(**tc.arguments)
                    conversation.add(
                        Message.tool_result(tc.id, result_text, name=tc.name)
                    )
                except Exception as e:
                    logger.warning("Tool %s failed: %s", tc.name, e)
                    conversation.add(
                        Message.tool_result(
                            tc.id,
                            f"Error: {e}",
                            is_error=True,
                            name=tc.name,
                        )
                    )

        return TaskResult(
            task_id=task.id,
            status=TaskStatus.MAX_STEPS,
            output=f"Reached maximum steps ({max_steps})",
            steps_taken=steps,
            tool_calls_made=tool_calls_total,
            duration_seconds=time.time() - t0,
        )
