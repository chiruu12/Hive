"""Tests for model registry pricing."""

from math import isclose
from pathlib import Path

from hive.models.registry import estimate_cost, load_model_registry

MODELS_YAML = Path(__file__).resolve().parents[1] / "models.yaml"


def test_fireworks_serverless_prices_load_from_yaml():
    registry = load_model_registry(MODELS_YAML)

    expected = {
        "accounts/fireworks/models/kimi-k2p6": (0.00095, 0.004),
        "accounts/fireworks/models/minimax-m2p7": (0.00030, 0.00120),
        "accounts/fireworks/models/deepseek-v3p2": (0.00056, 0.00168),
        "accounts/fireworks/models/gpt-oss-120b": (0.00015, 0.00060),
    }

    for model_id, (input_rate, output_rate) in expected.items():
        rates = registry.cost_per_1k(model_id)
        assert rates == {"input": input_rate, "output": output_rate}


def test_estimate_cost_uses_registry_prices():
    load_model_registry(MODELS_YAML)

    assert isclose(
        estimate_cost(
            "accounts/fireworks/models/kimi-k2p6",
            input_tokens=2_000,
            output_tokens=500,
        ),
        0.0039,
    )
