"""Tests for Groq provider routing, registry, and diagnostics."""

from __future__ import annotations

from unittest.mock import patch

from hive.daemon.diagnostics import check_groq_key
from hive.models.factory import create_runtime_provider
from hive.models.groq import Groq
from hive.models.registry import load_model_registry
from hive.models.router import detect_models


class TestGroqProviderRouting:
    def test_create_provider_groq(self) -> None:
        with patch("hive.config.get_env", return_value="gsk-test"):
            p = create_runtime_provider("groq:llama-3.3-70b-versatile")
        assert isinstance(p, Groq)
        assert p._model == "llama-3.3-70b-versatile"
        assert p._base_url == "https://api.groq.com/openai/v1"

    def test_groq_prefix_stripped(self) -> None:
        with patch("hive.config.get_env", return_value="gsk-test"):
            p = create_runtime_provider("groq:gemma2-9b-it")
        assert p._model == "gemma2-9b-it"

    def test_groq_available_with_key(self) -> None:
        with patch("hive.config.get_env", return_value="gsk-test"):
            p = create_runtime_provider("groq:llama-3.1-8b-instant")
        assert p.available

    def test_groq_unavailable_without_key(self) -> None:
        with patch("hive.config.get_env", return_value=""):
            p = create_runtime_provider("groq:llama-3.1-8b-instant")
        assert not p.available


class TestGroqRegistry:
    def test_groq_models_loaded(self) -> None:
        reg = load_model_registry()
        assert len(reg.groq) >= 1
        ids = [m.id for m in reg.groq]
        assert "groq:llama-3.3-70b-versatile" in ids

    def test_groq_in_all_models(self) -> None:
        reg = load_model_registry()
        providers = {p for p, _ in reg.all_models()}
        assert "groq" in providers

    def test_groq_cost_lookup(self) -> None:
        reg = load_model_registry()
        rates = reg.cost_per_1k("groq:llama-3.3-70b-versatile")
        assert rates["input"] > 0
        assert rates["output"] > 0


class TestGroqDetection:
    def test_detect_models_includes_groq(self) -> None:
        with patch("hive.config.get_env") as mock_env:
            mock_env.side_effect = lambda k: "gsk-test" if k == "GROQ_API_KEY" else None
            models = detect_models()
        assert "Groq" in models
        assert len(models["Groq"]) >= 1
        assert models["Groq"][0].available


class TestGroqDiagnostics:
    def test_check_with_key(self) -> None:
        with patch("hive.daemon.diagnostics.get_env", return_value="gsk-test"):
            result = check_groq_key()
        assert result.status == "ok"

    def test_check_without_key(self) -> None:
        with patch("hive.daemon.diagnostics.get_env", return_value=None):
            result = check_groq_key()
        assert result.status == "warn"
