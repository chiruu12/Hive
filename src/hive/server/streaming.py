"""SSE bridge: turn an Agent's push-style on_text callback into an async stream."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from hive.runtime.types import Task

if TYPE_CHECKING:
    from hive.agents.state import AgentState
    from hive.server.deps import ServerContext


async def stream_task(
    ctx: ServerContext, agent: AgentState, instruction: str, session_id: str, max_steps: int
) -> AsyncIterator[dict[str, str]]:
    """Yield SSE events: an optional ``info`` notice, ``token`` deltas, then a
    terminal ``done``/``error``.

    The Agent pushes text via ``on_text``; we funnel it through a queue so the
    coroutine running the task and the response stream stay decoupled. A sentinel
    closes the stream when the run finishes. When guardrails are enabled, token
    deltas are suppressed and a single ``info`` event is emitted up-front.
    """
    from hive.server.runner import build_oneshot_agent

    queue: asyncio.Queue[str | None] = asyncio.Queue()
    # Output guardrails (e.g. PII redaction) only run on the final result, but token
    # deltas are raw. Streaming them would leak the unredacted content the
    # non-streaming path masks. So when guardrails are enabled, don't forward token
    # deltas -- the terminal `done` event still carries the redacted final output.
    stream_tokens = not ctx.config.guardrails.enabled
    on_text = (lambda t: queue.put_nowait(t)) if stream_tokens else None
    runtime_agent = build_oneshot_agent(ctx, agent, session_id, on_text=on_text)

    # Tell the client up-front when token streaming is intentionally suppressed, so a
    # guardrailed run (which only emits the final `done`) is distinguishable from a
    # hung connection and the client can show a non-incremental progress indicator.
    if not stream_tokens:
        yield {"event": "info", "data": "token_streaming_suppressed_by_guardrails"}

    async def _run() -> None:
        try:
            result = await runtime_agent.run(Task(instruction=instruction, max_steps=max_steps))
            payload = json.dumps({"status": result.status, "output": result.output})
            queue.put_nowait("\x00" + payload)
        except Exception as exc:  # surfaced as an SSE error event
            queue.put_nowait("\x01" + str(exc))
        finally:
            queue.put_nowait(None)

    task = asyncio.create_task(_run())
    try:
        while True:
            item = await queue.get()
            if item is None:
                break
            if item.startswith("\x00"):
                yield {"event": "done", "data": item[1:]}
            elif item.startswith("\x01"):
                yield {"event": "error", "data": item[1:]}
            else:
                yield {"event": "token", "data": item}
    finally:
        if not task.done():
            task.cancel()
