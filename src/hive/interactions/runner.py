"""Scenario runner — executes any scenario end-to-end."""

import logging
from pathlib import Path
from typing import Any

from hive.interactions.base import (
    AgentSlot,
    InteractionPattern,
    MemoryStrategy,
    Message,
    RoundResult,
    Scenario,
    ScenarioResult,
)
from hive.interactions.registry import InteractionPatternRegistry, MemoryStrategyRegistry
from hive.interactions.transcript import Transcript
from hive.models.factory import create_runtime_provider
from hive.runtime.types import Message as RuntimeMessage

logger = logging.getLogger(__name__)


def create_pattern(name: str) -> InteractionPattern:
    registry = InteractionPatternRegistry.default()
    try:
        return registry.get(name)
    except KeyError:
        return registry.get("round_table")


def create_memory(name: str) -> MemoryStrategy:
    registry = MemoryStrategyRegistry.default()
    try:
        return registry.get(name)
    except KeyError:
        return registry.get("selective")


class ScenarioRunner:
    """Executes a scenario with any interaction pattern and memory strategy."""

    def __init__(
        self,
        scenario: Scenario,
        output_dir: Path | None = None,
        quiet: bool = False,
    ):
        self._scenario = scenario
        self._output_dir = output_dir
        self._transcript = Transcript(output_dir)
        self._quiet = quiet

    async def run(self) -> ScenarioResult:
        agents = self._scenario.setup()
        pattern = create_pattern(self._scenario.pattern_type)
        memories = {a.slot_id: create_memory(a.memory_type) for a in agents}

        history: list[RoundResult] = []
        total_tokens = 0
        total_cost = 0.0

        rounds_iter: Any = range(self._scenario.num_rounds)
        if self._quiet:
            from tqdm import tqdm

            rounds_iter = tqdm(rounds_iter, desc=self._scenario.name, unit="round")

        for r in rounds_iter:
            evidence = self._scenario.get_evidence(r)

            def context_builder(
                agent: AgentSlot,
                visible: list[Message],
                round_num: int,
                _memories: dict[str, MemoryStrategy] = memories,
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
            agents_iter: Any = agents
            if self._quiet:
                from tqdm import tqdm

                agents_iter = tqdm(agents, desc="Final actions", unit="agent")
            for agent in agents_iter:
                visible = pattern.get_visible_messages(agent.slot_id, history)
                mem = memories[agent.slot_id]
                mem_ctx = mem.build_context(agent, visible, self._scenario.num_rounds)
                prompt = self._scenario.get_final_prompt(agent, mem_ctx)

                provider = create_runtime_provider(agent.model)
                gen = await provider.generate_with_metadata(
                    messages=[
                        RuntimeMessage.system(agent.system_prompt),
                        RuntimeMessage.user(prompt),
                    ],
                    max_tokens=500,
                )
                total_tokens += gen.input_tokens + gen.output_tokens
                total_cost += gen.cost_usd or 0.0
                final_actions[agent.slot_id] = gen.message.content.strip()

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
            result.winner = max(scores, key=lambda k: scores[k])

        return result
