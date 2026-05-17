"""Instructions Deep Dive — all the ways to configure agent behavior.

Shows every way to set up an agent: plain string, Instructions class,
Persona class (with personality/values/fears and behavioral state),
with response_model, with context, and with toolkit instructions auto-merged.

Run: uv run python examples/13_instructions_deep_dive.py
"""

import asyncio

from pydantic import BaseModel

from hive import Agent, Instructions, Persona, Task
from hive.models.anthropic import Anthropic
from hive.tools import Toolkit, tool
from hive.tools.notepad import NotepadToolkit, Preset


# --- Custom toolkit with instructions that auto-merge ---
class AuditToolkit(Toolkit):
    """A toolkit that provides its own instructions to the agent."""

    @property
    def instructions(self) -> str:
        return (
            "You have access to an audit log. Every time you make a decision, "
            "record your reasoning using the log_decision tool."
        )

    @tool()
    def log_decision(self, decision: str, reasoning: str) -> str:
        """Log a decision with its reasoning.

        Args:
            decision: What you decided.
            reasoning: Why you decided it.
        """
        return f"Logged: {decision}"


# --- Structured output model ---
class Analysis(BaseModel):
    topic: str
    key_points: list[str]
    recommendation: str
    confidence: float


async def main() -> None:
    provider = Anthropic.lite()

    # --- 1. Plain string (simplest) ---
    print("=== 1. Plain string instructions ===\n")

    simple = Agent(
        name="helper",
        model=provider,
        instructions="You are a helpful assistant. Be concise.",
    )
    result = await simple.run(Task(instruction="What is Python's GIL?"))
    print(f"{result.output[:200]}\n")

    # --- 2. Instructions with persona + goals ---
    print("=== 2. Instructions with persona + goals ===\n")

    expert = Agent(
        name="expert",
        model=provider,
        instructions=Instructions(
            persona="a senior systems architect with 15 years of experience",
            instructions=[
                "Give practical, production-tested advice",
                "Consider trade-offs explicitly",
                "Mention relevant tools and patterns",
            ],
            context="The team is building a high-traffic e-commerce platform",
        ),
    )
    result = await expert.run(Task(instruction="Should we use a message queue? Which one?"))
    print(f"{result.output[:300]}\n")

    # --- 3. With response_model on Agent ---
    print("=== 3. Structured output via response_model ===\n")

    analyst = Agent(
        name="analyst",
        model=provider,
        instructions=Instructions(
            persona="a technology analyst",
            instructions=["Analyze topics objectively", "Rate your confidence"],
        ),
        response_model=Analysis,
    )
    result = await analyst.run_structured(
        Task(instruction="Analyze the adoption of Rust in backend development"),
        output_type=Analysis,
    )
    if result.parsed:
        print(f"Topic: {result.parsed.topic}")
        print(f"Points: {result.parsed.key_points}")
        print(f"Recommendation: {result.parsed.recommendation}")
        print(f"Confidence: {result.parsed.confidence}\n")

    # --- 4. Toolkit instructions auto-merge ---
    print("=== 4. Toolkit instructions auto-merged ===\n")

    audited = Agent(
        name="decision-maker",
        model=provider,
        instructions=Instructions(
            persona="a product manager making feature prioritization decisions",
        ),
        toolkits=[
            AuditToolkit(),
            NotepadToolkit(preset=Preset.journal()),
        ],
        max_steps=10,
    )

    # The system prompt now contains:
    # - Persona from Instructions
    # - AuditToolkit's instructions (auto-merged)
    # - NotepadToolkit's preset instructions (auto-merged)
    print(f"System prompt preview:\n{audited._system_prompt[:500]}\n")

    result = await audited.run(
        Task(
            instruction="Decide between building a mobile app "
            "or improving the web app. Log your reasoning."
        )
    )
    print(f"Output: {result.output[:200]}\n")

    # --- 5. Persona — agent with personality and behavioral state ---
    print("=== 5. Persona (personality + values + fears + behavioral state) ===\n")

    bold_agent = Agent(
        name="gambler",
        model=provider,
        persona=Persona(
            name="The Gambler",
            persona="a risk-taking strategist",
            personality=["bold", "intuitive", "comfortable with uncertainty"],
            values=["expected value", "asymmetric upside"],
            fears=["missing out", "becoming too cautious"],
            purpose="Find opportunities others are afraid to pursue",
            long_term_goals=["Build wealth through high-EV plays"],
            behavior_style="decisive",
            risk_tolerance=0.85,
            social_drive=0.6,
        ),
    )

    print(f"Persona prompt preview:\n{bold_agent._system_prompt[:400]}\n")

    result = await bold_agent.run(
        Task(
            instruction="You have $1000. A new cryptocurrency just launched "
            "with 10x potential but 80% chance of failure. What do you do?"
        )
    )
    print(f"Output: {result.output[:300]}")


if __name__ == "__main__":
    asyncio.run(main())
