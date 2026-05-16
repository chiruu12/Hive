"""Workflow Pipeline — chain multiple agents in a pipeline.

Each step's output feeds as context into the next step.
Great for multi-stage processing: research → draft → review → polish.

Run: uv run python examples/08_workflow_pipeline.py
"""

import asyncio

from hive import Agent, Step, Workflow
from hive.models.anthropic import Anthropic


async def main() -> None:
    provider = Anthropic.lite()

    researcher = Agent(
        name="researcher",
        model=provider,
        system_prompt=(
            "You are a technical researcher. Provide factual, well-organized "
            "information. Include specific details and examples."
        ),
    )

    writer = Agent(
        name="writer",
        model=provider,
        system_prompt=(
            "You are a technical writer. Take research notes and produce "
            "a clear, engaging blog post section. Use headers and bullet points."
        ),
    )

    editor = Agent(
        name="editor",
        model=provider,
        system_prompt=(
            "You are a copy editor. Review the draft for clarity, grammar, "
            "and technical accuracy. Return the polished final version."
        ),
    )

    workflow = Workflow(
        name="blog-post-pipeline",
        steps=[
            Step(
                name="research",
                agent=researcher,
                instruction=(
                    "Research the topic: {topic}. "
                    "Provide key facts, recent developments, and examples."
                ),
                output_key="research_notes",
            ),
            Step(
                name="draft",
                agent=writer,
                instruction=(
                    "Write a blog post section based on these research notes:\n\n{research_notes}"
                ),
                output_key="draft",
            ),
            Step(
                name="edit",
                agent=editor,
                instruction=(
                    "Edit and polish this draft. Fix any issues and improve readability:\n\n{draft}"
                ),
                output_key="final",
            ),
        ],
    )

    print("Running 3-stage pipeline: Research → Draft → Edit\n")

    result = await workflow.run({"topic": "WebAssembly and its impact on web development in 2025"})

    print("=== Research Notes ===")
    print(result.get("research_notes", "")[:500])
    print("\n=== Draft ===")
    print(result.get("draft", "")[:500])
    print("\n=== Final (edited) ===")
    print(result.get("final", "")[:500])


if __name__ == "__main__":
    asyncio.run(main())
