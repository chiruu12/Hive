"""Persona memory — filter messages by relevance to agent personality."""

import re

from hive.interactions.base import AgentSlot, MemoryStrategy, Message


class PersonaMemory(MemoryStrategy):
    def build_context(
        self, agent: AgentSlot, visible_messages: list[Message], round_num: int
    ) -> str:
        if not visible_messages:
            return "No messages yet."

        persona_tokens = _tokenize(agent.persona + " " + agent.role)
        scored: list[tuple[float, Message]] = []

        for m in visible_messages:
            msg_tokens = _tokenize(m.content)
            overlap = len(set(persona_tokens) & set(msg_tokens))
            relevance = overlap / max(len(persona_tokens), 1)
            if m.sender == agent.slot_id:
                relevance = 1.0
            if m.recipient == agent.slot_id:
                relevance = max(relevance, 0.8)
            scored.append((relevance, m))

        scored.sort(key=lambda x: (-x[0], x[1].round))
        top = scored[: min(15, len(scored))]
        top.sort(key=lambda x: x[1].round)

        lines = []
        for rel, m in top:
            prefix = f"[Round {m.round}] {m.sender}"
            if m.recipient != "all":
                prefix += f" → {m.recipient}"
            lines.append(f"{prefix}: {m.content[:200]}")

        return "\n".join(lines)


def _tokenize(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z]+", text.lower()) if len(w) > 3]
