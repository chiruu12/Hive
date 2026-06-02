"""Tests for the derived mood model (D3b)."""

from __future__ import annotations

import pytest

from hive.agents.mood import CircumplexMood, MoodModel, MoodRegistry, MoodState


@pytest.fixture(autouse=True)
def _reset_registry():
    MoodRegistry._reset()
    yield
    MoodRegistry._reset()


class TestCircumplexDerivation:
    def test_content_when_happy_and_calm(self) -> None:
        m = CircumplexMood().derive(happiness=0.8, suffering_load=0.0, in_crisis=False)
        assert m.label == "content"
        assert m.valence > 0 and m.arousal < 0.5

    def test_motivated_when_happy_and_activated(self) -> None:
        # High happiness still nets positive valence, but real suffering raises arousal.
        m = CircumplexMood().derive(happiness=0.9, suffering_load=0.55, in_crisis=False)
        assert m.label == "motivated"
        assert m.arousal >= 0.5 and m.valence >= 0.3

    def test_anxious_when_negative_and_activated(self) -> None:
        m = CircumplexMood().derive(happiness=0.2, suffering_load=0.7, in_crisis=False)
        assert m.label == "anxious"
        assert m.valence <= -0.3 and m.arousal >= 0.5

    def test_discouraged_when_negative_and_calm(self) -> None:
        m = CircumplexMood().derive(happiness=0.05, suffering_load=0.4, in_crisis=False)
        assert m.label == "discouraged"
        assert m.valence <= -0.3 and m.arousal < 0.5

    def test_steady_when_neutral_and_calm(self) -> None:
        m = CircumplexMood().derive(happiness=0.5, suffering_load=0.3, in_crisis=False)
        assert m.label == "steady"

    def test_restless_when_neutral_and_activated(self) -> None:
        m = CircumplexMood().derive(happiness=0.6, suffering_load=0.5, in_crisis=False)
        assert m.label == "restless"

    def test_crisis_overrides_to_overwhelmed(self) -> None:
        m = CircumplexMood().derive(happiness=0.9, suffering_load=0.95, in_crisis=True)
        assert m.label == "overwhelmed"
        assert m.arousal == 1.0

    def test_valence_and_arousal_clamped(self) -> None:
        m = CircumplexMood().derive(happiness=1.0, suffering_load=0.0, in_crisis=False)
        assert -1.0 <= m.valence <= 1.0
        assert 0.0 <= m.arousal <= 1.0


class TestPromptLine:
    def test_prompt_line_includes_label_and_note(self) -> None:
        state = MoodState("content", 0.8, 0.1, "satisfied; open to exploration")
        line = state.prompt_line()
        assert "content" in line and "satisfied" in line


class TestRegistry:
    def test_default_is_circumplex(self) -> None:
        assert isinstance(MoodRegistry.default().derive(0.7, 0.0, False), MoodState)

    def test_default_model_is_protocol_instance(self) -> None:
        assert isinstance(CircumplexMood(), MoodModel)

    def test_set_model_swaps_behavior(self) -> None:
        class AlwaysCalm:
            def derive(self, happiness: float, suffering_load: float, in_crisis: bool) -> MoodState:
                return MoodState("zen", 1.0, 0.0, "unflappable")

        MoodRegistry.default().set_model(AlwaysCalm())
        assert MoodRegistry.default().derive(0.0, 1.0, True).label == "zen"

    def test_set_model_rejects_invalid_object(self) -> None:
        with pytest.raises(TypeError):
            MoodRegistry.default().set_model(object())  # no derive() method
