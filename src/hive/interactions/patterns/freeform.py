"""Freeform — agents choose who to talk to, can whisper or broadcast."""

import json
import re
from typing import Any

from hive.interactions.base import (
    AgentSlot,
    InteractionPattern,
    Message,
    RoundResult,
)


class FreeformPattern(InteractionPattern):
    """Agents choose who to address. Can whisper (private) or broadcast."""

    async def run_round(
        self,
        agents: list[AgentSlot],
        round_num: int,
        history: list[RoundResult],
        context_builder: Any,
        provider_factory: Any,
    ) -> RoundResult:
        messages: list[Message] = []
        all_ids = [a.slot_id for a in agents]

        for agent in agents:
            visible = self.get_visible_messages(agent.slot_id, history)
            visible.extend([m for m in messages if agent.slot_id in m.visible_to])

            others = [f"{a.name} ({a.slot_id})" for a in agents if a.slot_id != agent.slot_id]
            choice_prompt = (
                f"\n\nOther agents: {', '.join(others)}\n"
                "You can address someone specific (whisper) or broadcast to all.\n"
                'Respond as JSON: {"to": "agent_id or all", "message": "your message"}\n'
            )

            memory_ctx = context_builder(agent, visible, round_num) + choice_prompt
            provider = provider_factory(agent.model)

            response = await provider.complete(
                messages=[{"role": "user", "content": memory_ctx}],
                system=agent.system_prompt,
                max_tokens=300,
            )

            recipient, content = self._parse_response(response.content, all_ids, agent.slot_id)

            if recipient == "all":
                vis = all_ids
            else:
                vis = [agent.slot_id, recipient]

            msg = Message(
                round=round_num,
                sender=agent.slot_id,
                recipient=recipient,
                content=content,
                visible_to=vis,
                tokens=response.input_tokens + response.output_tokens,
                cost_usd=response.cost_usd or 0.0,
            )
            messages.append(msg)

        return RoundResult(round_num=round_num, messages=messages)

    def get_visible_messages(self, agent_id: str, history: list[RoundResult]) -> list[Message]:
        visible = []
        for rr in history:
            for m in rr.messages:
                if not m.visible_to or agent_id in m.visible_to:
                    visible.append(m)
        return visible

    def _parse_response(self, text: str, all_ids: list[str], sender_id: str) -> tuple[str, str]:
        text = text.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            text = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])
        think = re.search(r"</think>\s*(.*)", text, re.DOTALL)
        if think:
            text = think.group(1).strip()
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end > start:
            try:
                data = json.loads(text[start : end + 1])
                to = data.get("to", "all")
                msg = data.get("message", text)
                if to not in all_ids and to != "all":
                    to = "all"
                return to, msg
            except json.JSONDecodeError:
                pass
        return "all", text
