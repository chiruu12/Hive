"""Agent with ReAct loop — the core of the Hive runtime."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from hive.logging.models import DecisionLog, ToolLog
from hive.models.base import BaseProvider
from hive.models.registry import estimate_cost
from hive.runtime.approval import ApprovalDecision, ApprovalGate, AwaitingApprovalSignal
from hive.runtime.guardrails import GuardrailAction, GuardrailPipeline, GuardrailStage
from hive.runtime.instructions import InstructionLike, Instructions
from hive.runtime.memory import ConversationMemory, PersistentMemory
from hive.runtime.persona import Persona
from hive.runtime.structured import StructuredGenerateResult
from hive.runtime.types import (
    GenerateResult,
    Message,
    StreamEventType,
    StructuredTaskResult,
    Task,
    TaskResult,
    TaskStatus,
)
from hive.tools.base import Tool, Toolkit, make_tool

if TYPE_CHECKING:
    from hive.logging.writer import LogWriter

logger = logging.getLogger(__name__)


def _coerce_tools(items: list[Any]) -> list[Tool]:
    """Convert Tool objects, @tool()-decorated functions, or plain callables to Tools."""
    result: list[Tool] = []
    for item in items:
        if isinstance(item, Tool):
            result.append(item)
        elif callable(item):
            result.append(make_tool(item))
        else:
            raise TypeError(f"Expected Tool or callable, got {type(item)}")
    return result


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
        tools: list[Tool | Any] | None = None,
        memory: PersistentMemory | None = None,
        max_steps: int = 25,
        temperature: float = 0.0,
        log_writer: LogWriter | None = None,
        agent_id: str = "",
        max_cost_usd: float = 0.0,
        max_tokens: int = 0,
        response_model: type[Any] | None = None,
        persona: Persona | None = None,
        conversation_log_dir: Path | str | None = None,
        on_text: Callable[[str], None] | None = None,
        on_tool: Callable[[str, dict[str, Any], bool], None] | None = None,
        tool_timeout: float = 0.0,
        approval_gate: ApprovalGate | None = None,
        guardrails: GuardrailPipeline | None = None,
        goal_id: str = "",
    ):
        self.name = name
        self._model = model
        self._on_text = on_text
        # Optional observability callback fired after each tool runs, with
        # (tool_name, arguments, ok). Used by evals to capture tool-call traces.
        self._on_tool = on_tool
        # Optional human-in-the-loop gate. When set, tools it flags are paused for
        # approval instead of executing (see _execute_tool_calls). None = no gating.
        self._approval_gate = approval_gate
        # Optional content guardrails. When set, the task input is checked before the
        # model runs (pre-hook) and the final output before it is returned (post-hook).
        self._guardrails = guardrails
        # Per-tool wall-clock limit (seconds); 0 disables. A tool that exceeds it
        # becomes a tool-error result so one hung tool can't stall the whole cycle.
        self._tool_timeout = tool_timeout
        self._toolkits = toolkits or []
        self._extra_tools = _coerce_tools(tools or [])
        self._memory = memory
        self._max_steps = max_steps
        self._temperature = temperature
        self._log_writer = log_writer
        self._agent_id = agent_id or name
        # Correlates this run's DecisionLog/ToolLog entries with the goal being
        # pursued (set by the daemon; empty for standalone/one-shot runs).
        self._goal_id = goal_id
        self._current_step = 0
        self._max_cost_usd = max_cost_usd
        self._max_tokens = max_tokens
        self._gen_max_tokens = max_tokens or 4096
        self._total_cost = 0.0
        self._total_tokens = 0
        self._cost_warned = False
        self._tokens_warned = False
        self._response_model = response_model
        self._conversation_log_dir = Path(conversation_log_dir) if conversation_log_dir else None

        import copy

        rebound: list[Toolkit] = []
        for tk in self._toolkits:
            if not tk.is_bound:
                tk.bind(self._agent_id)
                rebound.append(tk)
            elif tk._agent_id != self._agent_id:
                clone = copy.copy(tk)
                clone.rebind(self._agent_id)
                rebound.append(clone)
            else:
                rebound.append(tk)
        self._toolkits = rebound

        toolkit_instr = [tk.instructions for tk in self._toolkits if tk.instructions]

        # One protocol path for any instruction-like object (Instructions, Persona,
        # or a custom InstructionLike); the explicit persona arg takes precedence.
        # response_model is passed per-call, so the caller's object is never mutated.
        instruction_obj: InstructionLike | None = persona
        if instruction_obj is None and isinstance(instructions, InstructionLike):
            instruction_obj = instructions

        self._instructions: InstructionLike | None = instruction_obj
        if instruction_obj is not None:
            self._system_prompt = instruction_obj.build_system_prompt(toolkit_instr, response_model)
        else:
            if instructions and system_prompt:
                logger.warning(
                    "Agent %r: both 'instructions' and 'system_prompt' provided. "
                    "'instructions' takes precedence.",
                    name,
                )
            base = str(instructions) if instructions else system_prompt
            self._system_prompt = self._assemble_prompt(base, toolkit_instr, response_model)

    @staticmethod
    def _assemble_prompt(
        base: str,
        toolkit_instr: list[str],
        response_model: type[Any] | None,
    ) -> str:
        parts = [base] if base else []
        parts.extend(toolkit_instr)
        if response_model:
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

    def observe_tools(self, callback: Callable[[str, dict[str, Any], bool], None] | None) -> None:
        """Register (or clear with None) a callback fired after each tool runs.

        Receives ``(tool_name, arguments, ok)``. Used by the evals harness to capture
        an agent's tool-call trace without subclassing.
        """
        self._on_tool = callback

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
                logger.warning(
                    "Agent %r: persistent memory recall failed for task %s; "
                    "continuing without recalled memories (instruction: %.80s)",
                    self.name,
                    task.id,
                    task.instruction,
                    exc_info=True,
                )

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
        """Execute tool calls concurrently, then add results in order. Returns count.

        Tool calls within a single model turn run concurrently (``asyncio.gather``),
        so total wall-time is the slowest tool rather than the sum. Each call is
        isolated -- an unknown tool or a raised exception produces an error
        ``tool_result`` and log entry without affecting the others. Results are
        appended to the conversation in the original ``tool_calls`` order so
        transcripts and logs stay deterministic.
        """

        async def _run_one(tc: Any) -> dict[str, Any]:
            tool = tool_map.get(tc.name)

            if tool is None:
                available = ", ".join(tool_map.keys())
                logger.warning(
                    "Agent %r: unknown tool %r requested. Available: %s",
                    self.name,
                    tc.name,
                    available,
                )
                return {
                    "tc": tc,
                    "ok": False,
                    "result_text": f"Error: unknown tool '{tc.name}'. Available: {available}",
                    "log_result": "",
                    "error": "unknown tool",
                    "duration_ms": 0,
                }

            if self._approval_gate is not None and self._approval_gate.requires_approval(tool):
                approval = await self._approval_gate.check(tc.name, tc.arguments or {})
                if approval.decision is ApprovalDecision.DENIED:
                    reason = approval.reason or "no reason given"
                    return {
                        "tc": tc,
                        "ok": False,
                        "result_text": (
                            f"Tool '{tc.name}' was denied by a human reviewer: {reason}"
                        ),
                        "log_result": "",
                        "error": "denied",
                        "duration_ms": 0,
                    }
                if approval.decision is ApprovalDecision.PENDING:
                    return {
                        "tc": tc,
                        "ok": False,
                        "result_text": (
                            f"Awaiting human approval to run '{tc.name}' "
                            f"(approval {approval.approval_id})."
                        ),
                        "log_result": "",
                        "error": None,
                        "duration_ms": 0,
                        "pending_approval": approval.approval_id,
                    }
                # APPROVED: fall through and execute normally.

            tool_t0 = time.time()
            try:
                if self._tool_timeout > 0:
                    result_text = await asyncio.wait_for(
                        tool.call(**(tc.arguments or {})), timeout=self._tool_timeout
                    )
                else:
                    result_text = await tool.call(**(tc.arguments or {}))
                return {
                    "tc": tc,
                    "ok": True,
                    "result_text": result_text,
                    "log_result": result_text[:500],
                    "error": None,
                    "duration_ms": int((time.time() - tool_t0) * 1000),
                }
            except TimeoutError:
                logger.warning(
                    "Agent %r: tool %r timed out after %.1fs (args %s)",
                    self.name,
                    tc.name,
                    self._tool_timeout,
                    tc.arguments,
                )
                return {
                    "tc": tc,
                    "ok": False,
                    "result_text": (
                        f"Error: tool '{tc.name}' timed out after {self._tool_timeout:g}s"
                    ),
                    "log_result": "",
                    "error": "timeout",
                    "duration_ms": int((time.time() - tool_t0) * 1000),
                }
            except Exception as e:
                logger.warning(
                    "Agent %r: tool %r failed with args %s: %s",
                    self.name,
                    tc.name,
                    tc.arguments,
                    e,
                    exc_info=True,
                )
                return {
                    "tc": tc,
                    "ok": False,
                    "result_text": f"Error: {e}",
                    "log_result": "",
                    "error": str(e),
                    "duration_ms": int((time.time() - tool_t0) * 1000),
                }

        outcomes = await asyncio.gather(*(_run_one(tc) for tc in tool_calls))

        for outcome in outcomes:
            tc = outcome["tc"]
            conversation.add(
                Message.tool_result(
                    tc.id,
                    outcome["result_text"],
                    is_error=not outcome["ok"],
                    name=tc.name,
                )
            )
            self._log_tool(
                tc.name,
                tc.arguments,
                outcome["ok"],
                outcome["log_result"],
                outcome["error"],
                outcome["duration_ms"],
            )
            if self._on_tool is not None and not outcome.get("pending_approval"):
                self._on_tool(tc.name, tc.arguments or {}, outcome["ok"])

        # If any call is awaiting approval, the round is blocked. Every tool_use now
        # has a matching tool_result (appended above), so the transcript stays
        # well-formed; raise so run() can park the agent with the pending ids.
        pending_ids = [o["pending_approval"] for o in outcomes if o.get("pending_approval")]
        if pending_ids:
            raise AwaitingApprovalSignal(pending_ids)

        return len(tool_calls)

    async def _generate_message(
        self,
        messages: list[Message],
        tool_schemas: list[dict[str, Any]] | None,
    ) -> GenerateResult:
        """Generate one assistant turn, streaming text to ``on_text`` if configured.

        When an ``on_text`` callback is set and the provider supports streaming,
        text deltas are forwarded as they arrive and the terminal DONE event's
        result drives the rest of the loop. Otherwise this is a plain
        ``generate_with_metadata`` call.
        """
        if self._on_text is None:
            return await self._model.generate_with_metadata(
                messages=messages,
                tools=tool_schemas,
                temperature=self._temperature,
                max_tokens=self._gen_max_tokens,
            )

        final: GenerateResult | None = None
        accumulated: list[str] = []
        stream = self._model.generate_stream(
            messages=messages,
            tools=tool_schemas,
            temperature=self._temperature,
            max_tokens=self._gen_max_tokens,
        )
        try:
            async for event in stream:
                if event.type == StreamEventType.TEXT and event.text:
                    accumulated.append(event.text)
                    self._on_text(event.text)
                elif event.type == StreamEventType.DONE and event.result is not None:
                    final = event.result
        except Exception as e:
            # Mid-stream failure. Text already shown can't be replayed, so surface
            # what streamed; if nothing streamed yet, fall back to a (retried)
            # non-streaming call. CancelledError is BaseException, so it is not
            # caught here -- it propagates after the stream is closed in finally.
            if accumulated:
                logger.warning(
                    "Agent %r: stream failed after partial text; using it: %s", self.name, e
                )
                return self._synthesize_stream_result("".join(accumulated))
            logger.warning(
                "Agent %r: stream failed before any text; falling back to non-streaming: %s",
                self.name,
                e,
            )
            return await self._model.generate_with_metadata(
                messages=messages,
                tools=tool_schemas,
                temperature=self._temperature,
                max_tokens=self._gen_max_tokens,
            )
        finally:
            aclose = getattr(stream, "aclose", None)
            if aclose is not None:
                await aclose()

        if final is not None:
            return final
        # Stream ended without a terminal DONE event.
        if accumulated:
            logger.warning(
                "Agent %r: stream ended without a DONE event; using accumulated text", self.name
            )
            return self._synthesize_stream_result("".join(accumulated))
        logger.warning(
            "Agent %r: stream produced no events; falling back to non-streaming", self.name
        )
        return await self._model.generate_with_metadata(
            messages=messages,
            tools=tool_schemas,
            temperature=self._temperature,
            max_tokens=self._gen_max_tokens,
        )

    def _synthesize_stream_result(self, text: str) -> GenerateResult:
        """Build a GenerateResult from text already streamed to ``on_text``.

        Used when a stream is interrupted after emitting text but before the DONE
        event that carries usage. The partial text can't be replayed, so we return
        it as the turn's result (no tool calls). Real usage is unknown, so output
        tokens and cost are *estimated* from the streamed text (~4 chars/token) --
        otherwise the generation would be invisible to budget tracking and a
        near-limit agent could overshoot by a whole interrupted generation.
        """
        output_est = max(1, len(text) // 4) if text else 0
        return GenerateResult(
            message=Message.assistant(text),
            model=self._model.model,
            output_tokens=output_est,
            cost_usd=estimate_cost(self._model.model, 0, output_est),
        )

    async def run(self, task: Task) -> TaskResult:
        """Execute a task using the ReAct loop.

        Thin wrapper over the loop that stamps the run's accumulated cost and token
        totals onto the result (handy for evals and budgeting).
        """
        result = await self._run_loop(task)
        return result.model_copy(
            update={"cost_usd": self._total_cost, "total_tokens": self._total_tokens}
        )

    async def _run_loop(self, task: Task) -> TaskResult:
        """Execute a task using the ReAct loop."""
        self._total_cost = 0.0
        self._total_tokens = 0
        self._cost_warned = False
        self._tokens_warned = False
        t0 = time.time()

        # Pre-hook: inspect the task input before the model sees it. A blocking
        # guardrail (e.g. prompt injection) refuses the run; a redacting one rewrites
        # the instruction the model receives.
        if self._guardrails:
            finding = self._guardrails.run(task.instruction, GuardrailStage.INPUT)
            if finding.triggered:
                logger.warning(
                    "Agent %r: input guardrail %s (%s)",
                    self.name,
                    finding.action.value,
                    "; ".join(finding.reasons),
                )
                if finding.blocked:
                    return TaskResult(
                        task_id=task.id,
                        status=TaskStatus.FAILED,
                        output="",
                        error=f"blocked by guardrail: {'; '.join(finding.reasons)}",
                        duration_seconds=time.time() - t0,
                    )
                if finding.action is GuardrailAction.REDACT:
                    task = task.model_copy(update={"instruction": finding.text})

        tools = self.get_tools()
        tool_map = {t.name: t for t in tools}
        tool_schemas = [t.to_schema() for t in tools] if tools else None
        max_steps = task.max_steps or self._max_steps

        conversation = await self._prepare_conversation(task, max_steps)

        steps = 0
        tool_calls_total = 0

        while steps < max_steps:
            steps += 1
            self._current_step = steps

            try:
                result = await self._generate_message(conversation.get_messages(), tool_schemas)
                response = result.message
                self._log_decision(steps, result)
                self._total_tokens += result.input_tokens + result.output_tokens
                self._total_cost += result.cost_usd or 0.0
                self._check_budget_warning()
                budget_msg = self._check_budget()
                if budget_msg:
                    self._write_conversation_log(task.id, conversation.get_messages(), "failed")
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
                logger.error(
                    "Agent %r: model generation failed at step %d (model=%s): %s",
                    self.name,
                    steps,
                    self._model,
                    e,
                    exc_info=True,
                )
                self._log_decision_failure(steps, e)
                self._write_conversation_log(task.id, conversation.get_messages(), "failed")
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
                # Post-hook: inspect the final output before returning it. A blocking
                # guardrail withholds it; a redacting one masks matched spans (e.g. PII).
                output = response.content
                if self._guardrails:
                    finding = self._guardrails.run(output, GuardrailStage.OUTPUT)
                    if finding.triggered:
                        logger.warning(
                            "Agent %r: output guardrail %s (%s)",
                            self.name,
                            finding.action.value,
                            "; ".join(finding.reasons),
                        )
                        if finding.blocked:
                            output = "[output withheld by guardrail]"
                        elif finding.action is GuardrailAction.REDACT:
                            output = finding.text
                # The raw assistant message is already in the conversation; replace it
                # with the sanitized output for the on-disk log too, so a redacting
                # guardrail doesn't leak the unredacted content into the JSON log file.
                log_messages = conversation.get_messages()
                if output != response.content:
                    log_messages = [*log_messages[:-1], Message.assistant(output)]
                self._write_conversation_log(task.id, log_messages, "completed")
                return TaskResult(
                    task_id=task.id,
                    status=TaskStatus.COMPLETED,
                    output=output,
                    steps_taken=steps,
                    tool_calls_made=tool_calls_total,
                    duration_seconds=time.time() - t0,
                )

            try:
                tool_calls_total += await self._execute_tool_calls(
                    response.tool_calls, tool_map, conversation
                )
            except AwaitingApprovalSignal as signal:
                self._write_conversation_log(
                    task.id, conversation.get_messages(), "waiting_approval"
                )
                return TaskResult(
                    task_id=task.id,
                    status=TaskStatus.WAITING_APPROVAL,
                    output="Awaiting human approval: " + ", ".join(signal.approval_ids),
                    approval_ids=list(signal.approval_ids),
                    steps_taken=steps,
                    tool_calls_made=tool_calls_total,
                    duration_seconds=time.time() - t0,
                )

        self._write_conversation_log(task.id, conversation.get_messages(), "max_steps")
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
            structured: StructuredGenerateResult[Any] = await self._model.generate_structured(
                messages,
                output_type=output_type,
                temperature=self._temperature,
                max_tokens=self._gen_max_tokens,
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
                parsed=None,
            )

    async def run_once(
        self,
        message: str,
        context: str | None = None,
        max_tool_rounds: int = 5,
    ) -> str:
        """Run a request with automatic tool-call looping. No persistence.

        Loops until the model returns a text response or max_tool_rounds
        is reached, so multi-step tool chains complete naturally.

        Args:
            message: The user message to process.
            context: Optional extra context injected as a system message.
            max_tool_rounds: Max tool-call rounds before forcing a text response.

        Returns:
            The agent's final text response.
        """
        if max_tool_rounds < 0:
            raise ValueError(f"max_tool_rounds must be >= 0, got {max_tool_rounds}")

        self._total_cost = 0.0
        self._total_tokens = 0
        self._cost_warned = False
        self._tokens_warned = False

        tools = self.get_tools()
        tool_map = {t.name: t for t in tools}
        tool_schemas = [t.to_schema() for t in tools] if tools else None

        messages: list[Message] = []
        if self._system_prompt:
            messages.append(Message.system(self._system_prompt))
        if context:
            messages.append(Message.system(context))
        messages.append(Message.user(message))

        for _ in range(max_tool_rounds):
            result = await self._model.generate_with_metadata(
                messages,
                tool_schemas,
                self._temperature,
                self._gen_max_tokens,
            )
            response = result.message
            self._total_tokens += result.input_tokens + result.output_tokens
            self._total_cost += result.cost_usd or 0.0
            self._check_budget_warning()
            budget_msg = self._check_budget()
            if budget_msg:
                messages.append(response)
                self._write_conversation_log("run_once", messages, "budget_exceeded")
                return budget_msg

            if not response.tool_calls:
                messages.append(response)
                self._write_conversation_log("run_once", messages, "completed")
                return response.content

            messages.append(response)
            for tc in response.tool_calls:
                tool = tool_map.get(tc.name)
                if tool:
                    try:
                        output = await tool.call(**(tc.arguments or {}))
                    except Exception as e:
                        output = f"Error: {e}"
                else:
                    output = f"Unknown tool: {tc.name}"
                messages.append(Message.tool_result(tc.id, output))

        # Enforce the budget before the wrap-up generation too -- otherwise an
        # agent that exhausts its tool rounds near the limit would still spend one
        # more (previously unguarded) call.
        budget_msg = self._check_budget()
        if budget_msg:
            self._write_conversation_log("run_once", messages, "budget_exceeded")
            return budget_msg

        # Tool budget exhausted: nudge toward a plain-text wrap-up so the model doesn't
        # emit another tool call on this no-tools request (which strict providers reject).
        # The nudge is a user-role message (mid-thread system messages are rejected by some
        # strict providers) sent only for this call -- it isn't appended to the logged
        # conversation. The adapter's text-only recovery is the real safety net.
        wrap_up_messages = [
            *messages,
            Message.user(
                "Your tool budget is exhausted. Answer the user in plain text. "
                "Do not call any tools."
            ),
        ]
        final_result = await self._model.generate_with_metadata(
            wrap_up_messages,
            None,
            self._temperature,
            self._gen_max_tokens,
        )
        self._total_tokens += final_result.input_tokens + final_result.output_tokens
        self._total_cost += final_result.cost_usd or 0.0
        messages.append(final_result.message)
        self._write_conversation_log("run_once", messages, "completed")
        return final_result.message.content

    def run_once_sync(
        self,
        message: str,
        context: str | None = None,
        max_tool_rounds: int = 5,
    ) -> str:
        """Synchronous version of run_once."""
        try:
            asyncio.get_running_loop()
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(
                    asyncio.run,
                    self.run_once(message, context, max_tool_rounds),
                ).result()
        except RuntimeError:
            return asyncio.run(self.run_once(message, context, max_tool_rounds))

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

        result: StructuredGenerateResult[Any] = await self._model.generate_structured(
            messages,
            output_type=output_type,
            temperature=self._temperature,
            max_tokens=self._gen_max_tokens,
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

    def _write_conversation_log(
        self,
        task_id: str,
        messages: list[Message],
        status: str,
    ) -> None:
        """Write conversation to JSON file. Failures are silently logged."""
        if not self._conversation_log_dir:
            return
        try:
            from uuid import uuid4

            agent_dir = self._conversation_log_dir / self._agent_id
            agent_dir.mkdir(parents=True, exist_ok=True)
            timestamp = time.strftime("%Y%m%dT%H%M%S")
            path = agent_dir / f"{timestamp}_{uuid4().hex[:6]}.json"
            log_data = {
                "agent_id": self._agent_id,
                "agent_name": self.name,
                "task_id": task_id,
                "timestamp": timestamp,
                "model": str(self._model),
                "total_cost_usd": self._total_cost,
                "total_tokens": self._total_tokens,
                "status": status,
                "messages": [
                    {
                        "role": msg.role.value if hasattr(msg.role, "value") else str(msg.role),
                        "content": msg.content,
                        "tool_calls": [
                            {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                            for tc in (msg.tool_calls or [])
                        ],
                        "tool_call_id": msg.tool_call_id,
                    }
                    for msg in messages
                ],
            }
            path.write_text(json.dumps(log_data, indent=2, default=str))
        except Exception:
            logger.debug("Failed to write conversation log", exc_info=True)

    def _check_budget(self) -> str | None:
        """Return an error message if budget exceeded, None otherwise.

        Checked after each generation. A budget can therefore overshoot by at
        most one generation (cost/tokens are only known once a call returns); a
        projected pre-stop was evaluated but rejected because estimating with the
        full output cap falsely refuses small-budget agents that emit short
        replies.
        """
        if self._max_cost_usd and self._total_cost >= self._max_cost_usd:
            return f"Cost budget exceeded: ${self._total_cost:.4f} >= ${self._max_cost_usd:.4f}"
        if self._max_tokens and self._total_tokens >= self._max_tokens:
            return f"Token budget exceeded: {self._total_tokens:,} >= {self._max_tokens:,}"
        return None

    def _check_budget_warning(self) -> None:
        """Log a warning once per budget type when 80% is consumed."""
        cost_over = self._max_cost_usd and self._total_cost >= self._max_cost_usd * 0.8
        if not self._cost_warned and cost_over:
            logger.warning(
                "Agent %r approaching cost limit: $%.4f / $%.4f (%.0f%%)",
                self.name,
                self._total_cost,
                self._max_cost_usd,
                (self._total_cost / self._max_cost_usd) * 100,
            )
            self._cost_warned = True
        tok_over = self._max_tokens and self._total_tokens >= self._max_tokens * 0.8
        if not self._tokens_warned and tok_over:
            logger.warning(
                "Agent %r approaching token limit: %d / %d (%.0f%%)",
                self.name,
                self._total_tokens,
                self._max_tokens,
                (self._total_tokens / self._max_tokens) * 100,
            )
            self._tokens_warned = True

    def _log_decision(self, step: int, result: GenerateResult) -> None:
        if not self._log_writer:
            return
        self._log_writer.log_decision(
            DecisionLog(
                agent_id=self._agent_id,
                goal_id=self._goal_id,
                step_index=step,
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
                goal_id=self._goal_id,
                step_index=step,
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
                goal_id=self._goal_id,
                step_index=self._current_step,
                tool_name=name,
                params_raw=params,
                success=success,
                output=output[:500],
                error=error,
                duration_ms=duration_ms,
            )
        )
