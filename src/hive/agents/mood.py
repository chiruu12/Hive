"""Mood model — a derived emotional state from happiness + suffering (D3b).

An opt-in simulation layer that maps an agent's positive signal (``happiness``)
and aversive load (``suffering``) onto a valence/arousal circumplex (Russell's
model) and names the resulting mood, so the agent's current emotional state can
colour its behaviour in the prompt.

The mood is **pure and derived** -- it adds no persisted state. The default
``CircumplexMood`` can be swapped via ``MoodRegistry`` (the same extension
pattern as ``StressorRegistry``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Protocol, runtime_checkable


@dataclass(frozen=True)
class MoodState:
    """A named emotional state on the valence/arousal circumplex.

    valence: -1 (negative) .. +1 (positive). arousal: 0 (calm) .. 1 (activated).
    """

    label: str
    valence: float
    arousal: float
    note: str

    def prompt_line(self) -> str:
        """One-line descriptor for the system prompt / pursuit context."""
        return f"Current mood: {self.label} — {self.note}"


@runtime_checkable
class MoodModel(Protocol):
    """Derives a MoodState from the agent's positive/aversive signals."""

    def derive(self, happiness: float, suffering_load: float, in_crisis: bool) -> MoodState: ...


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


class CircumplexMood:
    """Default mood model.

    Valence is the positive signal net of aversive load; arousal rises with
    suffering and pegs at the top in a crisis. The (valence, arousal) point is
    then named by quadrant, with a crisis override.
    """

    def derive(self, happiness: float, suffering_load: float, in_crisis: bool) -> MoodState:
        valence = _clamp(happiness - suffering_load, -1.0, 1.0)
        arousal = 1.0 if in_crisis else _clamp(suffering_load, 0.0, 1.0)

        if in_crisis:
            return MoodState("overwhelmed", valence, arousal, "in crisis — focus inward on relief")

        activated = arousal >= 0.5
        if valence >= 0.3:
            if activated:
                return MoodState("motivated", valence, arousal, "energized; take initiative")
            return MoodState("content", valence, arousal, "satisfied; open to exploration")
        if valence <= -0.3:
            if activated:
                return MoodState("anxious", valence, arousal, "on edge; resolve stressors first")
            return MoodState("discouraged", valence, arousal, "low energy; favour small wins")
        if activated:
            return MoodState("restless", valence, arousal, "unsettled; pick a concrete next step")
        return MoodState("steady", valence, arousal, "balanced and focused")


class MoodRegistry:
    """Holds the active MoodModel. Swap the default to change mood derivation."""

    _instance: ClassVar[MoodRegistry | None] = None

    def __init__(self) -> None:
        self._model: MoodModel = CircumplexMood()

    def set_model(self, model: MoodModel) -> None:
        self._model = model

    def derive(self, happiness: float, suffering_load: float, in_crisis: bool) -> MoodState:
        return self._model.derive(happiness, suffering_load, in_crisis)

    @classmethod
    def default(cls) -> MoodRegistry:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def _reset(cls) -> None:
        cls._instance = None
