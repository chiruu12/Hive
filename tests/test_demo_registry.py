"""Tests for the demo registry."""

from __future__ import annotations

import pytest

from hive.demos.registry import DemoResult, list_demos, run_demo


class TestDemoRegistry:
    def test_list_demos_returns_dict(self):
        demos = list_demos()
        assert isinstance(demos, dict)
        assert "survival" in demos or "detective" in demos

    def test_demo_descriptions_are_strings(self):
        for name, desc in list_demos().items():
            assert isinstance(desc, str)
            assert len(desc) > 0

    def test_run_unknown_demo_raises(self):
        with pytest.raises(KeyError, match="Unknown demo"):
            run_demo("nonexistent_demo_xyz")

    def test_demo_result_dataclass(self):
        result = DemoResult(
            name="test",
            cycles=5,
            agents=["a", "b"],
            summary="done",
        )
        assert result.name == "test"
        assert result.cycles == 5
        assert len(result.agents) == 2
