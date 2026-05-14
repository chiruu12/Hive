"""Round table — all agents see all messages, take turns speaking."""

from typing import Any

from hive.interactions.base import (
    AgentSlot,
    InteractionPattern,
    Message,
    RoundResult,
)
from hive.runtime.types import Message as RuntimeMessage


class RoundTablePattern(InteractionPattern):
    """All agents see all messages. Each speaks once per round, in order."""

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
            visible.extend(messages)

            memory_ctx = context_builder(agent, visible, round_num)
            provider = provider_factory(agent.model)

            result = await provider.generate_with_metadata(
                messages=[
                    RuntimeMessage.system(agent.system_prompt),
                    RuntimeMessage.user(memory_ctx),
                ],
                max_tokens=300,
            )

            msg = Message(
                round=round_num,
                sender=agent.slot_id,
                recipient="all",
                content=result.message.content.strip(),
                visible_to=all_ids,
                tokens=result.input_tokens + result.output_tokens,
                cost_usd=result.cost_usd or 0.0,
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
