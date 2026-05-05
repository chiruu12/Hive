"""Claude CLI subprocess wrapper - implements ModelProvider via Claude Code CLI."""

import asyncio
import json
import logging
import shutil
from collections.abc import AsyncIterator
from pathlib import Path

from hive.models._protocol import (
    AssistantMessage,
    InboundMessage,
    ResultMessage,
    SystemInit,
    parse_ndjson_line,
)
from hive.models.protocol import ModelResponse, PlanStep

logger = logging.getLogger(__name__)


class ClaudeCLIProvider:
    """ModelProvider using Claude Code CLI subprocess.

    Spawns `claude` in print mode (-p) with NDJSON streaming.
    Claude handles tool execution autonomously — we observe and record.
    """

    def __init__(
        self,
        model: str = "claude-sonnet-4-6",
        max_turns: int = 10,
        session_timeout: int = 300,
    ):
        self._model = model
        self._max_turns = max_turns
        self._session_timeout = session_timeout
        self._session_id: str | None = None
        self._cli_path = shutil.which("claude") or "claude"

    @property
    def name(self) -> str:
        return "claude-cli"

    @property
    def available(self) -> bool:
        return shutil.which("claude") is not None

    async def complete(
        self,
        messages: list[dict[str, str]],
        system: str | None = None,
        tools: list[dict] | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> ModelResponse:
        """Send a message and collect the full response."""
        last_message = messages[-1]["content"] if messages else ""

        full_text = ""
        input_tokens = 0
        output_tokens = 0

        async for event in self.run_task(last_message, system_prompt=system or ""):
            if isinstance(event, AssistantMessage):
                full_text += event.text
            elif isinstance(event, ResultMessage):
                input_tokens = event.input_tokens or 0
                output_tokens = event.output_tokens or 0

        return ModelResponse(
            content=full_text,
            model=self._model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            stop_reason="end_turn",
        )

    async def plan(
        self,
        objective: str,
        available_tools: list[str],
        context: str | None = None,
    ) -> list[PlanStep]:
        """Ask Claude to produce a structured execution plan."""
        tools_str = ", ".join(available_tools) if available_tools else "none"
        prompt = (
            f"Create a step-by-step plan to accomplish this task.\n\n"
            f"Task: {objective}\n"
            f"Available tools: {tools_str}\n"
        )
        if context:
            prompt += f"Context: {context}\n"
        prompt += (
            "\nRespond with ONLY a JSON array of steps. Each step has: "
            '{"tool": "tool_name", "params": {...}, "rationale": "why"}\n'
            "No markdown, no explanation, just the JSON array."
        )

        response = await self.complete(
            messages=[{"role": "user", "content": prompt}],
            system="You are a planning agent. Output only valid JSON.",
        )

        try:
            steps_data = json.loads(response.content.strip())
            return [PlanStep(**step) for step in steps_data]
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning("Failed to parse plan response: %s", e)
            return []

    async def run_task(
        self,
        task: str,
        system_prompt: str = "",
        cwd: str | None = None,
    ) -> AsyncIterator[InboundMessage]:
        """Spawn Claude with a task and yield NDJSON events as they stream."""
        cmd = [
            self._cli_path,
            "-p",
            "--output-format",
            "stream-json",
            "--verbose",
            "--permission-mode",
            "acceptEdits",
            "--model",
            self._model,
            "--max-turns",
            str(self._max_turns),
        ]

        if self._session_id:
            cmd.extend(["--resume", self._session_id])

        if system_prompt:
            cmd.extend(["--append-system-prompt", system_prompt])

        work_dir = cwd or str(Path.cwd())

        logger.info(
            "Spawning Claude: model=%s cwd=%s resume=%s",
            self._model,
            work_dir,
            self._session_id,
        )

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=work_dir,
        )

        if proc.stdin:
            proc.stdin.write(task.encode("utf-8"))
            proc.stdin.close()

        try:
            async for event in self._read_stdout(proc):
                if isinstance(event, SystemInit) and event.session_id:
                    self._session_id = event.session_id
                yield event
        finally:
            if proc.returncode is None:
                try:
                    await asyncio.wait_for(proc.wait(), timeout=self._session_timeout)
                except TimeoutError:
                    logger.warning("Claude process timed out, killing")
                    proc.kill()
                    await proc.wait()

    async def _read_stdout(self, proc: asyncio.subprocess.Process) -> AsyncIterator[InboundMessage]:
        stdout = proc.stdout
        if stdout is None:
            return

        while True:
            line_bytes = await stdout.readline()
            if not line_bytes:
                break

            line = line_bytes.decode("utf-8", errors="replace")
            event = parse_ndjson_line(line)
            if event is not None:
                yield event
