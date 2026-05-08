"""Full memory — agent sees complete transcript of visible messages."""

from hive.interactions.base import AgentSlot, MemoryStrategy, Message


class FullMemory(MemoryStrategy):
    def build_context(
        self, agent: AgentSlot, visible_messages: list[Message], round_num: int
    ) -> str:
        if not visible_messages:
            return "No messages yet."
        lines = []
        for m in visible_messages:
            prefix = f"[Round {m.round}] {m.sender}"
            if m.recipient != "all":
                prefix += f" → {m.recipient}"
            lines.append(f"{prefix}: {m.content}")
        return "\n".join(lines)
