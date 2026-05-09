"""Exchange runner — lightweight interaction orchestrator using Participants."""

from __future__ import annotations

import logging
import random

from hive.interactions.base import (
    ExchangeConfig,
    ExchangeResult,
    InteractionMessage,
    Participant,
)

logger = logging.getLogger(__name__)


class ExchangeRunner:
    """Runs an interaction exchange between participants."""

    def __init__(self, config: ExchangeConfig):
        self._config = config

    async def run(self, participants: list[Participant]) -> ExchangeResult:
        result = ExchangeResult(
            participant_ids=[p.participant_id for p in participants],
        )
        history: list[InteractionMessage] = []

        for r in range(self._config.num_rounds):
            round_msgs = await self._run_round(participants, r, history)
            history.extend(round_msgs)
            result.messages.extend(round_msgs)
            logger.info("Round %d: %d messages", r, len(round_msgs))

        result.rounds_completed = self._config.num_rounds
        return result

    async def _run_round(
        self,
        participants: list[Participant],
        round_num: int,
        history: list[InteractionMessage],
    ) -> list[InteractionMessage]:
        pattern = self._config.pattern
        if pattern == "pairs":
            return await self._round_pairs(participants, round_num, history)
        if pattern == "freeform":
            return await self._round_freeform(participants, round_num, history)
        return await self._round_table(participants, round_num, history)

    async def _round_table(
        self,
        participants: list[Participant],
        round_num: int,
        history: list[InteractionMessage],
    ) -> list[InteractionMessage]:
        """All see all, each speaks once in order."""
        messages: list[InteractionMessage] = []
        all_ids = tuple(p.participant_id for p in participants)
        context = self._config.topic or self._config.context

        for participant in participants:
            visible = [
                m for m in history + messages
                if not m.visible_to or participant.participant_id in m.visible_to
            ]

            content = await participant.respond(
                visible, context=context,
            )

            messages.append(
                InteractionMessage(
                    round=round_num,
                    sender_id=participant.participant_id,
                    sender_name=participant.name,
                    content=content,
                    recipient_id="all",
                    visible_to=all_ids,
                )
            )

        return messages

    async def _round_pairs(
        self,
        participants: list[Participant],
        round_num: int,
        history: list[InteractionMessage],
    ) -> list[InteractionMessage]:
        """1-on-1 paired conversations, partners rotate each round."""
        messages: list[InteractionMessage] = []
        context = self._config.topic or self._config.context

        shuffled = list(participants)
        rng = random.Random(round_num * 42)
        rng.shuffle(shuffled)

        pairs = []
        for i in range(0, len(shuffled) - 1, 2):
            pairs.append((shuffled[i], shuffled[i + 1]))
        if len(shuffled) % 2 == 1:
            pairs.append((shuffled[-1], shuffled[0]))

        for p1, p2 in pairs:
            pair_ids = (p1.participant_id, p2.participant_id)

            visible = [
                m for m in history
                if not m.visible_to or p1.participant_id in m.visible_to
            ]
            c1 = await p1.respond(visible, context=context)
            msg1 = InteractionMessage(
                round=round_num,
                sender_id=p1.participant_id,
                sender_name=p1.name,
                content=c1,
                recipient_id=p2.participant_id,
                visible_to=pair_ids,
            )
            messages.append(msg1)

            visible2 = [
                m for m in history
                if not m.visible_to or p2.participant_id in m.visible_to
            ]
            visible2.append(msg1)
            c2 = await p2.respond(visible2, context=context)
            messages.append(
                InteractionMessage(
                    round=round_num,
                    sender_id=p2.participant_id,
                    sender_name=p2.name,
                    content=c2,
                    recipient_id=p1.participant_id,
                    visible_to=pair_ids,
                )
            )

        return messages

    async def _round_freeform(
        self,
        participants: list[Participant],
        round_num: int,
        history: list[InteractionMessage],
    ) -> list[InteractionMessage]:
        """Each participant speaks when ready, can address anyone."""
        messages: list[InteractionMessage] = []
        all_ids = tuple(p.participant_id for p in participants)
        context = self._config.topic or self._config.context

        for participant in participants:
            visible = [
                m for m in history + messages
                if not m.visible_to or participant.participant_id in m.visible_to
            ]

            content = await participant.respond(visible, context=context)
            messages.append(
                InteractionMessage(
                    round=round_num,
                    sender_id=participant.participant_id,
                    sender_name=participant.name,
                    content=content,
                    recipient_id="all",
                    visible_to=all_ids,
                )
            )

        return messages
