"""Comms toolkit — inter-agent messaging via inbox files."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from hive.runtime.guardrails import sanitize_inter_agent_content
from hive.tools.base import Toolkit, tool

if TYPE_CHECKING:
    from hive.runtime.guardrails import GuardrailPipeline

logger = logging.getLogger(__name__)


class CommsToolkit(Toolkit):
    """Inter-agent messaging via inbox files.

    Usage:
        tk = CommsToolkit()                          # defaults to .hive/comms/
        tk = CommsToolkit(path="/my/comms/dir")       # explicit path
    """

    def __init__(
        self,
        path: str | Path | None = None,
        agent_id: str = "",
        guardrails: GuardrailPipeline | None = None,
    ):
        self._comms_dir = Path(path) if path else Path.cwd() / ".hive" / "comms"
        self._comms_dir.mkdir(parents=True, exist_ok=True)
        self._agent_id = agent_id
        self._guardrails = guardrails

    def _sanitize_message(self, content: str) -> str:
        """Run INPUT guardrails on inter-agent message content."""
        return sanitize_inter_agent_content(content, self._guardrails, agent_id=self._agent_id)

    def _ensure_id(self) -> str:
        if not self._agent_id:
            self._agent_id = f"agent-{uuid4().hex[:8]}"
        return self._agent_id

    @tool()
    def send_message(self, target_agent: str, message: str) -> str:
        """Send a message to another agent.

        Args:
            target_agent: The ID of the agent to message.
            message: The message content.
        """
        inbox = self._comms_dir / f"{target_agent}_inbox.jsonl"
        entry = json.dumps(
            {
                "from": self._ensure_id(),
                "message": message,
                "ts": datetime.now(UTC).isoformat(),
            }
        )
        with open(inbox, "a") as f:
            f.write(entry + "\n")
        return f"Sent to {target_agent}"

    @tool()
    def read_inbox(self) -> str:
        """Read all messages in your inbox from other agents."""
        inbox = self._comms_dir / f"{self._ensure_id()}_inbox.jsonl"
        if not inbox.exists():
            return "No messages."
        lines = inbox.read_text().strip().splitlines()
        if not lines:
            return "No messages."
        messages = []
        for line in lines:
            try:
                msg = json.loads(line)
                body = self._sanitize_message(msg.get("message", ""))
                messages.append(f"[{msg.get('ts', '?')}] {msg['from']}: {body}")
            except json.JSONDecodeError:
                continue
        return "\n".join(messages) if messages else "No messages."
