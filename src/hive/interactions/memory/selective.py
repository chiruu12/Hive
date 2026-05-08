"""Selective memory — own messages verbatim, others summarized per round."""

from hive.interactions.base import AgentSlot, MemoryStrategy, Message


class SelectiveMemory(MemoryStrategy):
    def build_context(
        self, agent: AgentSlot, visible_messages: list[Message], round_num: int
    ) -> str:
        if not visible_messages:
            return "No messages yet."

        own = [m for m in visible_messages if m.sender == agent.slot_id]
        others = [m for m in visible_messages if m.sender != agent.slot_id]

        lines = []

        by_round: dict[int, list[Message]] = {}
        for m in others:
            by_round.setdefault(m.round, []).append(m)

        for r in sorted(by_round):
            msgs = by_round[r]
            senders = {m.sender for m in msgs}
            topics = set()
            for m in msgs:
                words = m.content.lower().split()
                for w in words:
                    if len(w) > 5:
                        topics.add(w[:20])
            topic_str = ", ".join(list(topics)[:5]) if topics else "general discussion"
            lines.append(f"[Round {r}] {', '.join(senders)} discussed: {topic_str}")

        if own:
            lines.append("\nYour previous statements:")
            for m in own[-10:]:
                lines.append(f"  [Round {m.round}] You said: {m.content[:150]}")

        return "\n".join(lines)
