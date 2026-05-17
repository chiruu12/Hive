"""Agent with ReAct loop — the core of the Hive runtime."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any

from hive.logging.models import DecisionLog, ToolLog
from hive.models.base import BaseProvider
from hive.runtime.instructions import Instructions
from hive.runtime.memory import ConversationMemory, PersistentMemory
from hive.runtime.structured import StructuredGenerateResult, generate_structured_fallback
from hive.runtime.types import (
    GenerateResult,
    Message,
    StructuredTaskResult,
    Task,
    TaskResult,
    TaskStatus,
)
from hive.tools.base import Tool, Toolkit

if TYPE_CHECKING:
    from hive.logging.writer import LogWriter

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
        model: BaseProvider,
        instructions: Instructions | str = "",
        system_prompt: str = "",
        toolkits: list[Toolkit] | None = None,
        tools: list[Tool] | None = None,
        memory: PersistentMemory | None = None,
        max_steps: int = 25,
        temperature: float = 0.0,
        log_writer: LogWriter | None = None,
        agent_id: str = "",
        max_cost_usd: float = 0.0,
        max_tokens: int = 0,
        response_model: type[Any] | None = None,
    ):
        self.name = name
        self._model = model
        self._toolkits = toolkits or []
        self._extra_tools = tools or []
        self._memory = memory
        self._max_steps = max_steps
        self._temperature = temperature
        self._log_writer = log_writer
        self._agent_id = agent_id or name
        self._max_cost_usd = max_cost_usd
        self._max_tokens = max_tokens
        self._gen_max_tokens = max_tokens or 4096
        self._total_cost = 0.0
        self._total_tokens = 0
        self._response_model = response_model

        for tk in self._toolkits:
            tk.bind(self._agent_id)

        toolkit_instr = [tk.instructions for tk in self._toolkits if tk.instructions]

        if isinstance(instructions, Instructions):
            instr_copy = Instructions(
                persona=instructions.persona,
                instructions=list(instructions.goals),
                context=instructions.context,
            )
            if response_model:
                instr_copy.response_model = response_model
            self._instructions: Instructions | None = instr_copy
            self._system_prompt = instr_copy.build_system_prompt(toolkit_instr)
        else:
            if instructions and system_prompt:
                logger.warning(
                    "Agent %r: both 'instructions' and 'system_prompt' provided. "
                    "'instructions' takes precedence.",
                    name,
                )
            self._instructions = None
            base = str(instructions) if instructions else system_prompt
            self._system_prompt = self._assemble_prompt(
                base, toolkit_instr, response_model
            )

    @staticmethod
    def _assemble_prompt(
        base: str,
        toolkit_instr: list[str],
        response_model: type[Any] | None,
    ) -> str:
        parts = [base] if base else []
        parts.extend(toolkit_instr)
        if response_model:
            import json

            schema = response_model.model_json_schema()
            schema.pop("title", None)
            parts.append(
                "Respond with a JSON object matching this schema:\n"
                f"```json\n{json.dumps(schema, indent=2)}\n```"
            )
        return "\n\n".join(parts)

    def __repr__(self) -> str:
        return (
            f"Agent(name={self.name!r}, model={self._model.__class__.__name__}, "
            f"tools={len(self.get_tools())}, max_steps={self._max_steps})"
        )

    def __str__(self) -> str:
        return f"Agent({self.name})"

    def get_tools(self) -> list[Tool]:
        """Return all tools available to this agent."""
        all_tools: list[Tool] = list(self._extra_tools)
        for tk in self._toolkits:
            all_tools.extend(tk.get_tools())
        seen: dict[str, int] = {}
        for t in all_tools:
            seen[t.name] = seen.get(t.name, 0) + 1
        duplicates = [name for name, count in seen.items() if count > 1]
        if duplicates:
            logger.warning(
                "Agent %r has duplicate tool names: %s. Last definition wins.",
                self.name,
                duplicates,
            )
        return all_tools

    async def _prepare_conversation(self, task: Task, max_steps: int) -> ConversationMemory:
        """Build the initial conversation with system prompt, memories, and task."""
        conversation = ConversationMemory(
            system_prompt=self._system_prompt,
            max_messages=max_steps * 4,
        )

        if self._memory:
            try:
                relevant = await self._memory.recall(task.instruction, limit=3)
                if relevant:
                    context_lines = [
                        f"- {m.get('thought', m.get('content', str(m)))}" for m in relevant
                    ]
                    conversation.add(
                        Message.system("Relevant memories:\n" + "\n".join(context_lines))
                    )
            except Exception:
                logger.debug("Failed to recall persistent memory", exc_info=True)

        if task.context:
            context_str = "\n".join(f"{k}: {v}" for k, v in task.context.items())
            conversation.add(Message.user(f"{task.instruction}\n\nContext:\n{context_str}"))
        else:
            conversation.add(Message.user(task.instruction))

        return conversation

    async def _execute_tool_calls(
        self,
        tool_calls: tuple[Any, ...],
        tool_map: dict[str, Tool],
        conversation: ConversationMemory,
    ) -> int:
        """Execute tool calls and add results to conversation. Returns count."""
        count = 0
        for tc in tool_calls:
            count += 1
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
                self._log_tool(tc.name, tc.arguments, False, "", "unknown tool", 0)
                continue

            tool_t0 = time.time()
            try:
                result_text = await tool.call(**tc.arguments)
                conversation.add(Message.tool_result(tc.id, result_text, name=tc.name))
                self._log_tool(
                    tc.name,
                    tc.arguments,
                    True,
                    result_text[:500],
                    None,
                    int((time.time() - tool_t0) * 1000),
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
                self._log_tool(
                    tc.name,
                    tc.arguments,
                    False,
                    "",
                    str(e),
                    int((time.time() - tool_t0) * 1000),
                )
        return count

    async def run(self, task: Task) -> TaskResult:
        """Execute a task using the ReAct loop."""
        self._total_cost = 0.0
        self._total_tokens = 0
        t0 = time.time()

        tools = self.get_tools()
        tool_map = {t.name: t for t in tools}
        tool_schemas = [t.to_schema() for t in tools] if tools else None
        max_steps = task.max_steps or self._max_steps

        conversation = await self._prepare_conversation(task, max_steps)

        steps = 0
        tool_calls_total = 0

        while steps < max_steps:
            steps += 1

            try:
                result = await self._model.generate_with_metadata(
                    messages=conversation.get_messages(),
                    tools=tool_schemas,
                    temperature=self._temperature,
                    max_tokens=self._gen_max_tokens,
                )
                response = result.message
                self._log_decision(steps, result)
                self._total_tokens += result.input_tokens + result.output_tokens
                self._total_cost += result.cost_usd or 0.0
                budget_msg = self._check_budget()
                if budget_msg:
                    return TaskResult(
                        task_id=task.id,
                        status=TaskStatus.FAILED,
                        output=response.content,
                        error=budget_msg,
                        steps_taken=steps,
                        tool_calls_made=tool_calls_total,
                        duration_seconds=time.time() - t0,
                    )
            except Exception as e:
                logger.error("Model generation failed: %s", e)
                self._log_decision_failure(steps, e)
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

            tool_calls_total += await self._execute_tool_calls(
                response.tool_calls, tool_map, conversation
            )

        return TaskResult(
            task_id=task.id,
            status=TaskStatus.MAX_STEPS,
            output=f"Reached maximum steps ({max_steps})",
            steps_taken=steps,
            tool_calls_made=tool_calls_total,
            duration_seconds=time.time() - t0,
        )

    async def run_structured(
        self,
        task: Task,
        output_type: type[Any],
    ) -> StructuredTaskResult[Any]:
        """One-shot structured output — returns a validated Pydantic model."""
        self._total_cost = 0.0
        self._total_tokens = 0
        t0 = time.time()
        messages: list[Message] = []
        if self._system_prompt:
            messages.append(Message.system(self._system_prompt))
        if task.context:
            context_str = "\n".join(f"{k}: {v}" for k, v in task.context.items())
            messages.append(Message.user(f"{task.instruction}\n\nContext:\n{context_str}"))
        else:
            messages.append(Message.user(task.instruction))

        try:
            if hasattr(self._model, "generate_structured"):
                structured: StructuredGenerateResult[Any] = await self._model.generate_structured(
                    messages,
                    output_type=output_type,
                    temperature=self._temperature,
                    max_tokens=self._gen_max_tokens,
                )
            else:
                structured = await generate_structured_fallback(
                    self._model,
                    messages,
                    output_type,
                    self._temperature,
                    self._gen_max_tokens,
                )

            return StructuredTaskResult(
                task_id=task.id,
                status=TaskStatus.COMPLETED,
                output=structured.result.message.content,
                steps_taken=1,
                duration_seconds=time.time() - t0,
                parsed=structured.parsed,
            )
        except Exception as e:
            logger.error("Structured generation failed: %s", e)
            return StructuredTaskResult(
                task_id=task.id,
                status=TaskStatus.FAILED,
                output="",
                error=str(e),
                steps_taken=1,
                duration_seconds=time.time() - t0,
                parsed=output_type.model_construct(),
            )

    async def run_once(
        self,
        message: str,
        context: str | None = None,
    ) -> str:
        """Run a single request-response cycle. No persistence.

        Args:
            message: The user message to process.
            context: Optional extra context injected as a system message.

        Returns:
            The agent's final text response.
        """
        tools = self.get_tools()
        tool_map = {t.name: t for t in tools}
        tool_schemas = [t.to_schema() for t in tools] if tools else None

        messages: list[Message] = []
        if self._system_prompt:
            messages.append(Message.system(self._system_prompt))
        if context:
            messages.append(Message.system(context))
        messages.append(Message.user(message))

        result = await self._model.generate_with_metadata(
            messages,
            tool_schemas,
            self._temperature,
            self._gen_max_tokens,
        )
        response = result.message

        if not response.tool_calls:
            return response.content

        messages.append(response)
        for tc in response.tool_calls:
            tool = tool_map.get(tc.name)
            if tool:
                try:
                    output = await tool.call(**tc.arguments)
                except Exception as e:
                    output = f"Error: {e}"
            else:
                output = f"Unknown tool: {tc.name}"
            messages.append(Message.tool_result(tc.id, output))

        final = await self._model.generate(
            messages,
            tool_schemas,
            self._temperature,
            self._gen_max_tokens,
        )
        return final.content

    def run_once_sync(
        self,
        message: str,
        context: str | None = None,
    ) -> str:
        """Synchronous version of run_once."""
        try:
            asyncio.get_running_loop()
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(
                    asyncio.run,
                    self.run_once(message, context),
                ).result()
        except RuntimeError:
            return asyncio.run(self.run_once(message, context))

    async def run_once_structured(
        self,
        message: str,
        output_type: type[Any],
        context: str | None = None,
    ) -> Any:
        """One-shot structured output. Returns a validated Pydantic model.

        Args:
            message: The user message to process.
            output_type: Pydantic model class for the response.
            context: Optional extra context injected as a system message.

        Returns:
            An instance of output_type validated from the LLM response.
        """
        messages: list[Message] = []
        if self._system_prompt:
            messages.append(Message.system(self._system_prompt))
        if context:
            messages.append(Message.system(context))
        messages.append(Message.user(message))

        if hasattr(self._model, "generate_structured"):
            result: StructuredGenerateResult[Any] = await self._model.generate_structured(
                messages,
                output_type=output_type,
                temperature=self._temperature,
                max_tokens=self._gen_max_tokens,
            )
        else:
            result = await generate_structured_fallback(
                self._model,
                messages,
                output_type,
                self._temperature,
                self._gen_max_tokens,
            )
        return result.parsed

    def run_once_structured_sync(
        self,
        message: str,
        output_type: type[Any],
        context: str | None = None,
    ) -> Any:
        """Synchronous version of run_once_structured."""
        try:
            asyncio.get_running_loop()
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(
                    asyncio.run,
                    self.run_once_structured(message, output_type, context),
                ).result()
        except RuntimeError:
            return asyncio.run(
                self.run_once_structured(message, output_type, context),
            )

    def _check_budget(self) -> str | None:
        """Return an error message if budget exceeded, None otherwise."""
        if self._max_cost_usd and self._total_cost >= self._max_cost_usd:
            return f"Cost budget exceeded: ${self._total_cost:.4f} >= ${self._max_cost_usd:.4f}"
        if self._max_tokens and self._total_tokens >= self._max_tokens:
            return f"Token budget exceeded: {self._total_tokens:,} >= {self._max_tokens:,}"
        return None

    def _log_decision(self, step: int, result: GenerateResult) -> None:
        if not self._log_writer:
            return
        self._log_writer.log_decision(
            DecisionLog(
                agent_id=self._agent_id,
                decision_type="react_step",
                model=result.model,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                cost_usd=result.cost_usd,
                duration_ms=result.duration_ms,
                response_raw=result.message.content,
                success=True,
            )
        )

    def _log_decision_failure(self, step: int, error: Exception) -> None:
        if not self._log_writer:
            return
        self._log_writer.log_decision(
            DecisionLog(
                agent_id=self._agent_id,
                decision_type="react_step",
                success=False,
                response_raw=str(error),
            )
        )

    def _log_tool(
        self,
        name: str,
        params: dict[str, Any],
        success: bool,
        output: str,
        error: str | None,
        duration_ms: int,
    ) -> None:
        if not self._log_writer:
            return
        self._log_writer.log_tool(
            ToolLog(
                agent_id=self._agent_id,
                tool_name=name,
                params_raw=params,
                success=success,
                output=output[:500],
                error=error,
                duration_ms=duration_ms,
            )
        )
