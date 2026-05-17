"""Plugin loader — discover and load Toolkit plugins from directories."""

from __future__ import annotations

import importlib.util
import logging
import sys
from pathlib import Path

from hive.tools.base import Toolkit

logger = logging.getLogger(__name__)


class PluginLoader:
    """Scan directories for Python files that export Toolkit subclasses."""

    def __init__(self, plugin_dirs: list[Path]):
        self._dirs = plugin_dirs
        self._loaded: dict[str, type[Toolkit]] = {}
        self._seen_files: set[Path] = set()

    def discover(self) -> list[type[Toolkit]]:
        """Scan plugin directories and return newly found Toolkit classes."""
        new_toolkits: list[type[Toolkit]] = []
        for d in self._dirs:
            if not d.is_dir():
                continue
            for py_file in sorted(d.glob("*.py")):
                if py_file.name.startswith("_"):
                    continue
                if py_file in self._seen_files:
                    continue
                self._seen_files.add(py_file)
                try:
                    tks = self._load_module(py_file)
                    new_toolkits.extend(tks)
                except Exception as e:
                    logger.warning(
                        "Failed to load plugin %s: %s",
                        py_file.name,
                        e,
                    )
        return new_toolkits

    def _load_module(self, path: Path) -> list[type[Toolkit]]:
        """Import a Python file and extract Toolkit subclasses."""
        module_name = f"hive_plugin_{path.stem}"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            return []
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)

        toolkits: list[type[Toolkit]] = []
        for attr_name in dir(module):
            obj = getattr(module, attr_name)
            if (
                isinstance(obj, type)
                and issubclass(obj, Toolkit)
                and obj is not Toolkit
                and attr_name not in self._loaded
            ):
                self._loaded[attr_name] = obj
                toolkits.append(obj)
                logger.info(
                    "Loaded plugin toolkit: %s from %s",
                    attr_name,
                    path.name,
                )
        return toolkits

    @property
    def loaded_count(self) -> int:
        return len(self._loaded)
