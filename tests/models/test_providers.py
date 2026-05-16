"""Tests for provider tier presets, factory routing, and repr."""

from __future__ import annotations

from unittest.mock import patch

from hive.models.anthropic import Anthropic
from hive.models.base import BaseProvider
from hive.models.factory import create_runtime_provider
from hive.models.fireworks import Fireworks
from hive.models.groq import Groq
from hive.models.lmstudio import LMStudio
from hive.models.ollama import Ollama
from hive.models.openai import OpenAI


def _patch_env(return_value: str = "test-key"):
    """Patch get_env to return a fake API key."""
    return patch("hive.config.get_env", return_value=return_value)


class TestTierPresets:
    """Verify that tier classmethods produce the correct model strings."""

    # --- Anthropic ---

    def test_anthropic_lite(self) -> None:
        with _patch_env():
            a = Anthropic.lite()
            assert a.model == "claude-haiku-4-5"
            assert isinstance(a, BaseProvider)

    def test_anthropic_standard(self) -> None:
        with _patch_env():
            a = Anthropic.standard()
            assert a.model == "claude-sonnet-4-6"

    def test_anthropic_pro(self) -> None:
        with _patch_env():
            a = Anthropic.pro()
            assert a.model == "claude-opus-4-6"

    # --- OpenAI ---

    def test_openai_lite(self) -> None:
        with _patch_env():
            o = OpenAI.lite()
            assert o.model == "gpt-5.4-nano"
            assert isinstance(o, BaseProvider)

    def test_openai_standard(self) -> None:
        with _patch_env():
            o = OpenAI.standard()
            assert o.model == "gpt-5.4-mini"

    # --- Groq ---

    def test_groq_lite(self) -> None:
        with _patch_env():
            g = Groq.lite()
            assert g.model == "llama-3.1-8b-instant"
            assert isinstance(g, BaseProvider)

    def test_groq_standard(self) -> None:
        with _patch_env():
            g = Groq.standard()
            assert g.model == "openai/gpt-oss-20b"

    # --- Fireworks ---

    def test_fireworks_lite(self) -> None:
        with _patch_env():
            f = Fireworks.lite()
            assert f.model == "accounts/fireworks/models/minimax-m2p7"
            assert isinstance(f, BaseProvider)

    def test_fireworks_standard(self) -> None:
        with _patch_env():
            f = Fireworks.standard()
            assert f.model == "accounts/fireworks/models/deepseek-v4-pro"

    def test_fireworks_pro(self) -> None:
        with _patch_env():
            f = Fireworks.pro()
            assert f.model == "accounts/fireworks/models/kimi-k2p6"

    # --- Ollama ---

    def test_ollama_lite(self) -> None:
        o = Ollama.lite()
        assert o.model == "llama3.2"
        assert isinstance(o, BaseProvider)

    # --- OpenAI pro ---

    def test_openai_pro(self) -> None:
        with _patch_env():
            o = OpenAI.pro()
            assert o.model == "gpt-5.4"

    # --- Groq pro ---

    def test_groq_pro(self) -> None:
        with _patch_env():
            g = Groq.pro()
            assert g.model == "llama-3.3-70b-versatile"

    # --- LMStudio ---

    def test_lmstudio_lite(self) -> None:
        lms = LMStudio.lite()
        assert lms.model == "loaded-model"
        assert isinstance(lms, BaseProvider)

    def test_lmstudio_standard(self) -> None:
        lms = LMStudio.standard()
        assert lms.model == "loaded-model"


class TestFactory:
    """Verify that create_runtime_provider routes model names to the right class."""

    def test_routes_claude(self) -> None:
        with _patch_env():
            p = create_runtime_provider("claude-haiku-4-5")
            assert isinstance(p, Anthropic)
            assert p.model == "claude-haiku-4-5"

    def test_routes_claude_sonnet(self) -> None:
        with _patch_env():
            p = create_runtime_provider("claude-sonnet-4-6")
            assert isinstance(p, Anthropic)

    def test_routes_gpt(self) -> None:
        with _patch_env():
            p = create_runtime_provider("gpt-5.4-nano")
            assert isinstance(p, OpenAI)
            assert p.model == "gpt-5.4-nano"

    def test_routes_fireworks(self) -> None:
        with _patch_env():
            p = create_runtime_provider("fireworks:accounts/fireworks/models/deepseek-v4-pro")
            assert isinstance(p, Fireworks)

    def test_routes_groq(self) -> None:
        with _patch_env():
            p = create_runtime_provider("groq:llama-3.3-70b-versatile")
            assert isinstance(p, Groq)
            assert p.model == "llama-3.3-70b-versatile"

    def test_routes_lmstudio(self) -> None:
        p = create_runtime_provider("lmstudio:my-model")
        assert isinstance(p, LMStudio)
        assert p.model == "my-model"

    def test_routes_ollama_prefix(self) -> None:
        p = create_runtime_provider("ollama:llama3.2")
        assert isinstance(p, Ollama)
        assert p.model == "llama3.2"

    def test_routes_unknown_to_ollama(self) -> None:
        p = create_runtime_provider("some-unknown-model")
        assert isinstance(p, Ollama)
        assert p.model == "some-unknown-model"

    def test_all_return_base_provider(self) -> None:
        with _patch_env():
            for model in [
                "claude-haiku-4-5",
                "gpt-5.4-nano",
                "groq:llama-3.1-8b-instant",
                "fireworks:accounts/fireworks/models/minimax-m2p7",
                "lmstudio:loaded-model",
                "ollama:llama3.2",
            ]:
                p = create_runtime_provider(model)
                assert isinstance(p, BaseProvider), f"{model} did not return a BaseProvider"


class TestRepr:
    """Verify provider __repr__ includes class name and model."""

    def test_anthropic_repr(self) -> None:
        with _patch_env():
            a = Anthropic.lite()
            r = repr(a)
            assert "Anthropic" in r
            assert "claude-haiku-4-5" in r

    def test_openai_repr(self) -> None:
        with _patch_env():
            o = OpenAI.lite()
            r = repr(o)
            assert "OpenAI" in r
            assert "gpt-5.4-nano" in r

    def test_groq_repr(self) -> None:
        with _patch_env():
            g = Groq.lite()
            r = repr(g)
            assert "Groq" in r
            assert "llama-3.1-8b-instant" in r

    def test_fireworks_repr(self) -> None:
        with _patch_env():
            f = Fireworks.lite()
            r = repr(f)
            assert "Fireworks" in r
            assert "minimax-m2p7" in r

    def test_ollama_repr(self) -> None:
        o = Ollama.lite()
        r = repr(o)
        assert "Ollama" in r
        assert "llama3.2" in r

    def test_lmstudio_repr(self) -> None:
        lms = LMStudio.lite()
        r = repr(lms)
        assert "LMStudio" in r
        assert "loaded-model" in r

    def test_base_repr_format(self) -> None:
        with _patch_env():
            a = Anthropic.lite()
            assert repr(a) == "Anthropic(model='claude-haiku-4-5')"

    def test_str_format(self) -> None:
        with _patch_env():
            a = Anthropic.lite()
            assert str(a) == "Anthropic(claude-haiku-4-5)"
