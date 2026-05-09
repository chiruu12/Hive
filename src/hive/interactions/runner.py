"""Scenario runner — executes any scenario end-to-end."""

import logging
from pathlib import Path

from hive.interactions.base import (
    AgentSlot,
    InteractionPattern,
    MemoryStrategy,
    Message,
    RoundResult,
    Scenario,
    ScenarioResult,
)
from hive.interactions.memory.full import FullMemory
from hive.interactions.memory.persona import PersonaMemory
from hive.interactions.memory.selective import SelectiveMemory
from hive.interactions.patterns.freeform import FreeformPattern
from hive.interactions.patterns.pairs import PairsPattern
from hive.interactions.patterns.round_table import RoundTablePattern
from hive.interactions.transcript import Transcript
from hive.runtime.providers import create_runtime_provider
from hive.runtime.types import Message as RuntimeMessage

logger = logging.getLogger(__name__)


def create_pattern(name: str) -> InteractionPattern:
    patterns = {
        "round_table": RoundTablePattern,
        "pairs": PairsPattern,
        "freeform": FreeformPattern,
    }
    cls = patterns.get(name, RoundTablePattern)
    return cls()


def create_memory(name: str) -> MemoryStrategy:
    strategies = {
        "full": FullMemory,
        "selective": SelectiveMemory,
        "persona": PersonaMemory,
    }
    cls = strategies.get(name, SelectiveMemory)
    return cls()


class ScenarioRunner:
    """Executes a scenario with any interaction pattern and memory strategy."""

    def __init__(
        self,
        scenario: Scenario,
        output_dir: Path | None = None,
    ):
        self._scenario = scenario
        self._output_dir = output_dir
        self._transcript = Transcript(output_dir)

    async def run(self) -> ScenarioResult:
        agents = self._scenario.setup()
        pattern = create_pattern(self._scenario.pattern_type)
        memories = {a.slot_id: create_memory(a.memory_type) for a in agents}

        history: list[RoundResult] = []
        total_tokens = 0
        total_cost = 0.0

        for r in range(self._scenario.num_rounds):
            evidence = self._scenario.get_evidence(r)

            def context_builder(
                agent: AgentSlot,
                visible: list[Message],
                round_num: int,
                _memories: dict = memories,
                _scenario: Scenario = self._scenario,
                _evidence: str = evidence,
            ) -> str:
                mem = _memories[agent.slot_id]
                mem_ctx = mem.build_context(agent, visible, round_num)
                prompt = _scenario.build_round_prompt(agent, round_num, mem_ctx)
                if _evidence:
                    prompt = f"[NEW EVIDENCE] {_evidence}\n\n{prompt}"
                return prompt

            rr = await pattern.run_round(
                agents, r, history, context_builder, create_runtime_provider
            )
            rr.evidence_revealed = evidence

            for m in rr.messages:
                total_tokens += m.tokens
                total_cost += m.cost_usd

            history.append(rr)
            self._transcript.add_round(rr)

            logger.info(
                "Round %d: %d messages, %d tokens",
                r,
                len(rr.messages),
                sum(m.tokens for m in rr.messages),
            )

        final_actions = {}
        if self._scenario.get_final_prompt(agents[0], ""):
            for agent in agents:
                visible = pattern.get_visible_messages(agent.slot_id, history)
                mem = memories[agent.slot_id]
                mem_ctx = mem.build_context(agent, visible, self._scenario.num_rounds)
                prompt = self._scenario.get_final_prompt(agent, mem_ctx)

                provider = create_runtime_provider(agent.model)
                result = await provider.generate_with_metadata(
                    messages=[
                        RuntimeMessage.system(agent.system_prompt),
                        RuntimeMessage.user(prompt),
                    ],
                    max_tokens=500,
                )
                total_tokens += result.input_tokens + result.output_tokens
                total_cost += result.cost_usd or 0.0
                final_actions[agent.slot_id] = result.message.content.strip()

        transcript_path = self._transcript.save(self._scenario.name)

        result = ScenarioResult(
            name=self._scenario.name,
            rounds=history,
            final_actions=final_actions,
            total_tokens=total_tokens,
            total_cost=total_cost,
            transcript_path=transcript_path,
        )

        scores = self._scenario.evaluate(result)
        result.scores = scores
        if scores:
            result.winner = max(scores, key=scores.get)

        return result
