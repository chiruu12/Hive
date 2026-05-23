"""Voice agent pattern — the blueprint for Mutter and other voice assistants.

Press Cmd+Shift+M to record voice → transcribe → classify intent → route to agent.

Requirements:
    pip install hive-agent[audio,hotkeys]
    # Plus one of: mlx-whisper (Apple Silicon) or set GROQ_API_KEY / DEEPGRAM_API_KEY

Usage:
    python examples/22_voice_agent.py
"""

from __future__ import annotations

import asyncio

from hive import (
    Agent,
    AlarmToolkit,
    Instructions,
    KnowledgeToolkit,
    TaskToolkit,
)
from hive.models.groq import Groq
from hive.routing import IntentRouter
from hive.stt import AudioRecorder, create_stt_provider
from hive.tools.links import LinkToolkit
from hive.triggers import HotkeyTrigger

# --- Setup ---

stt = create_stt_provider("groq")

router = IntentRouter(
    model=Groq.lite(),
    intents={
        "task": "user wants to create a todo item or manage tasks",
        "note": "user wants to save information or remember something",
        "query": "user is asking a question or wants information",
        "link": "user wants to save or look up a URL",
        "alarm": "user wants to set a timer or alarm",
        "agent": "user needs multi-step help or complex assistance",
    },
)

agent = Agent(
    name="voice-assistant",
    model=Groq.standard(),
    instructions=Instructions(
        persona="You are a helpful voice assistant. Keep responses concise.",
        instructions=["Respond in 1-2 sentences when possible."],
    ),
    toolkits=[
        TaskToolkit(db_path=".hive/voice.db"),
        KnowledgeToolkit(memory_dir=".hive"),
        AlarmToolkit(db_path=".hive/voice.db"),
        LinkToolkit(memory_dir=".hive"),
    ],
)

recorder = AudioRecorder(sample_rate=16000, channels=1)


async def process_voice() -> None:
    """Record → transcribe → classify → respond."""
    print("\n🎤 Recording... (press Cmd+Shift+M again to stop)")
    recorder.start()

    # In a real app, you'd wait for a second hotkey press or silence detection.
    # For this example, record for 5 seconds.
    await asyncio.sleep(5)

    audio_bytes = recorder.stop()
    print("📝 Transcribing...")

    result = await stt.transcribe_bytes(audio_bytes)
    print(f"   You said: {result.text}")

    if not result.text.strip():
        print("   (empty transcription, skipping)")
        return

    intent = await router.classify(result.text)
    print(f"   Intent: {intent.intent} ({intent.confidence:.0%})")

    response = await agent.run_once(result.text)
    print(f"   🤖 {response}")


def main() -> None:
    trigger = HotkeyTrigger()
    trigger.register("cmd+shift+m", process_voice, name="voice-input")
    trigger.start()

    print("Voice agent ready. Press Cmd+Shift+M to speak.")
    print("Press Ctrl+C to quit.\n")

    try:
        while True:
            pass
    except KeyboardInterrupt:
        trigger.stop()
        print("\nBye!")


if __name__ == "__main__":
    main()
