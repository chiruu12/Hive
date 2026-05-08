"""Pairs — agents interact 1-on-1, rotate partners each round."""

import logging
import random
from typing import Any

logger = logging.getLogger(__name__)

from hive.interactions.base import (
    AgentSlot,
    InteractionPattern,
    Message,
    RoundResult,
)


class PairsPattern(InteractionPattern):
    """Agents paired 1-on-1. Partners rotate each round."""

    async def run_round(
        self,
        agents: list[AgentSlot],
        round_num: int,
        history: list[RoundResult],
        context_builder: Any,
        provider_factory: Any,
    ) -> RoundResult:
        messages: list[Message] = []
        pairs = self._make_pairs(agents, round_num)

        for a, b in pairs:
            pair_ids = [a.slot_id, b.slot_id]

            for speaker, listener in [(a, b), (b, a)]:
                visible = self.get_visible_messages(speaker.slot_id, history)
                visible.extend([m for m in messages if speaker.slot_id in m.visible_to])

                memory_ctx = context_builder(speaker, visible, round_num)
                provider = provider_factory(speaker.model)

                response = await provider.complete(
                    messages=[{"role": "user", "content": memory_ctx}],
                    system=speaker.system_prompt,
                    max_tokens=300,
                )

                msg = Message(
                    round=round_num,
                    sender=speaker.slot_id,
                    recipient=listener.slot_id,
                    content=response.content.strip(),
                    visible_to=pair_ids,
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

    def _make_pairs(
        self, agents: list[AgentSlot], round_num: int
    ) -> list[tuple[AgentSlot, AgentSlot]]:
        shuffled = list(agents)
        if len(shuffled) < 2:
            return []
        rng = random.Random(round_num * 42)
        rng.shuffle(shuffled)
        pairs = []
        for i in range(0, len(shuffled) - 1, 2):
            pairs.append((shuffled[i], shuffled[i + 1]))
        if len(shuffled) % 2 == 1:
            leftover = shuffled[-1]
            partner = pairs[-1][0]
            pairs.append((leftover, partner))
            logger.debug("Odd agent count: %s paired with %s", leftover.slot_id, partner.slot_id)
        return pairs
