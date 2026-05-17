"""Tests for PluginLoader — dynamic Toolkit discovery from directories."""

from __future__ import annotations

from pathlib import Path

import pytest

from hive.runtime.plugin_loader import PluginLoader


def _write_plugin(path: Path, content: str) -> Path:
    path.write_text(content)
    return path


@pytest.fixture
def plugin_dir(tmp_path: Path) -> Path:
    d = tmp_path / "plugins"
    d.mkdir()
    return d


class TestPluginDiscovery:
    def test_discovers_toolkit_subclass(self, plugin_dir: Path) -> None:
        _write_plugin(
            plugin_dir / "greeting.py",
            """
from hive.tools import Toolkit, tool

class GreetingToolkit(Toolkit):
    @tool()
    def greet(self, name: str) -> str:
        return f"Hello, {name}!"
""",
        )
        loader = PluginLoader([plugin_dir])
        found = loader.discover()
        assert len(found) == 1
        assert found[0].__name__ == "GreetingToolkit"
        assert loader.loaded_count == 1

    def test_skips_underscore_prefixed(self, plugin_dir: Path) -> None:
        _write_plugin(
            plugin_dir / "_internal.py",
            """
from hive.tools import Toolkit, tool

class InternalToolkit(Toolkit):
    @tool()
    def secret(self) -> str:
        return "hidden"
""",
        )
        loader = PluginLoader([plugin_dir])
        found = loader.discover()
        assert len(found) == 0

    def test_ignores_non_toolkit_classes(self, plugin_dir: Path) -> None:
        _write_plugin(
            plugin_dir / "helper.py",
            """
class SomeHelper:
    pass

class AnotherClass:
    def do_stuff(self):
        pass
""",
        )
        loader = PluginLoader([plugin_dir])
        found = loader.discover()
        assert len(found) == 0

    def test_bad_plugin_logs_warning(
        self,
        plugin_dir: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        _write_plugin(plugin_dir / "broken.py", "raise RuntimeError('boom')")

        loader = PluginLoader([plugin_dir])
        found = loader.discover()
        assert len(found) == 0
        assert "Failed to load plugin broken.py" in caplog.text

    def test_same_file_not_loaded_twice(self, plugin_dir: Path) -> None:
        _write_plugin(
            plugin_dir / "once.py",
            """
from hive.tools import Toolkit, tool

class OnceToolkit(Toolkit):
    @tool()
    def ping(self) -> str:
        return "pong"
""",
        )
        loader = PluginLoader([plugin_dir])
        first = loader.discover()
        second = loader.discover()
        assert len(first) == 1
        assert len(second) == 0
        assert loader.loaded_count == 1

    def test_hot_reload_finds_new_files(self, plugin_dir: Path) -> None:
        _write_plugin(
            plugin_dir / "first.py",
            """
from hive.tools import Toolkit, tool

class FirstToolkit(Toolkit):
    @tool()
    def one(self) -> str:
        return "1"
""",
        )
        loader = PluginLoader([plugin_dir])
        first = loader.discover()
        assert len(first) == 1

        _write_plugin(
            plugin_dir / "second.py",
            """
from hive.tools import Toolkit, tool

class SecondToolkit(Toolkit):
    @tool()
    def two(self) -> str:
        return "2"
""",
        )
        second = loader.discover()
        assert len(second) == 1
        assert second[0].__name__ == "SecondToolkit"
        assert loader.loaded_count == 2

    def test_missing_directory_is_safe(self, tmp_path: Path) -> None:
        loader = PluginLoader([tmp_path / "nonexistent"])
        found = loader.discover()
        assert len(found) == 0

    def test_multiple_toolkits_in_one_file(
        self,
        plugin_dir: Path,
    ) -> None:
        _write_plugin(
            plugin_dir / "multi.py",
            """
from hive.tools import Toolkit, tool

class AlphaToolkit(Toolkit):
    @tool()
    def alpha(self) -> str:
        return "a"

class BetaToolkit(Toolkit):
    @tool()
    def beta(self) -> str:
        return "b"
""",
        )
        loader = PluginLoader([plugin_dir])
        found = loader.discover()
        assert len(found) == 2
        names = {t.__name__ for t in found}
        assert names == {"AlphaToolkit", "BetaToolkit"}
