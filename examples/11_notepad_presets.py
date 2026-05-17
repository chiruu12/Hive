"""Notepad Presets — agents with persistent memory and configurable behavior.

Shows how different presets guide what the agent writes to its notepad.
The notepad persists across runs — agents build up knowledge over time.

Run: uv run python examples/11_notepad_presets.py
"""

import asyncio

from hive import Agent, Instructions, Task
from hive.models.anthropic import Anthropic
from hive.tools.notepad import NotepadToolkit, Preset


async def main() -> None:
    provider = Anthropic.lite()

    # --- Journal preset: agent reflects on what it does ---

    journalist = Agent(
        name="researcher",
        model=provider,
        instructions=Instructions(
            persona="a research assistant",
            instructions=["Research topics thoroughly", "Write findings to your notepad"],
        ),
        toolkits=[NotepadToolkit(preset=Preset.journal())],
        max_steps=10,
    )

    result = await journalist.run(
        Task(
            instruction="Research the pros and cons of microservices vs monoliths. "
            "Write your findings to your notepad."
        )
    )
    print("=== Journal Agent ===")
    print(f"Output: {result.output[:200]}")
    print(f"Notepad:\n{journalist._toolkits[0].read_notepad()}\n")

    # --- Evolution preset: agent reflects on self-improvement ---

    learner = Agent(
        name="learner",
        model=provider,
        instructions=Instructions(
            persona="a junior developer learning to code",
            instructions=["Try to solve problems", "Reflect on what you learned"],
        ),
        toolkits=[NotepadToolkit(preset=Preset.evolution())],
        max_steps=10,
    )

    result = await learner.run(
        Task(
            instruction="Think about what makes good code. "
            "Write your reflections on how you could improve."
        )
    )
    print("=== Evolution Agent ===")
    print(f"Output: {result.output[:200]}")
    print(f"Notepad:\n{learner._toolkits[0].read_notepad()}\n")

    # --- Custom preset: user-defined behavior ---

    bug_tracker = Agent(
        name="tester",
        model=provider,
        instructions=Instructions(
            persona="a QA engineer",
            instructions=["Analyze code for bugs", "Log every bug found to your notepad"],
        ),
        toolkits=[
            NotepadToolkit(
                preset=Preset.custom("Log every bug: severity, description, repro steps.")
            )
        ],
        max_steps=10,
    )

    result = await bug_tracker.run(
        Task(
            instruction=(
                "Analyze this code for bugs and log them:\n\n"
                "```python\n"
                "def divide(a, b):\n"
                "    return a / b\n\n"
                "def get_item(lst, idx):\n"
                "    return lst[idx]\n"
                "```"
            )
        )
    )
    print("=== Custom Preset Agent ===")
    print(f"Output: {result.output[:200]}")
    print(f"Notepad:\n{bug_tracker._toolkits[0].read_notepad()}")


if __name__ == "__main__":
    asyncio.run(main())
