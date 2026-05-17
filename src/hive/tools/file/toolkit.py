"""File system toolkit — workspace-scoped file access for agents."""

from __future__ import annotations

import logging
from pathlib import Path

from hive.tools.base import Toolkit, tool

logger = logging.getLogger(__name__)


class FileToolkit(Toolkit):
    """File system access scoped to a workspace directory.

    Usage:
        tk = FileToolkit()                     # defaults to CWD
        tk = FileToolkit(workspace="/my/dir")   # explicit path
    """

    def __init__(self, workspace: str | Path | None = None):
        self._workspace = Path(workspace).resolve() if workspace else Path.cwd()
        self._workspace.mkdir(parents=True, exist_ok=True)

    def _resolve(self, path: str) -> Path:
        resolved = (self._workspace / path).resolve()
        if not resolved.is_relative_to(self._workspace):
            raise PermissionError(f"Path escapes workspace: {path}")
        return resolved

    @tool()
    def file_read(self, path: str, offset: int = 0, limit: int = 500) -> str:
        """Read a file from the workspace.

        Args:
            path: Relative path within the workspace.
            offset: Line number to start from (0-based).
            limit: Maximum number of lines to return.
        """
        resolved = self._resolve(path)
        if not resolved.exists():
            return f"Error: file not found: {path}"
        if resolved.is_dir():
            return f"Error: {path} is a directory, use list_dir"
        try:
            lines = resolved.read_text().splitlines()
            selected = lines[offset : offset + limit]
            numbered = [f"{i + offset + 1:4d} | {line}" for i, line in enumerate(selected)]
            header = f"# {path} (lines {offset + 1}-{offset + len(selected)} of {len(lines)})"
            return header + "\n" + "\n".join(numbered)
        except Exception as e:
            return f"Error reading {path}: {e}"

    @tool()
    def file_write(self, path: str, content: str) -> str:
        """Write content to a file in the workspace. Creates directories as needed.

        Args:
            path: Relative path within the workspace.
            content: The full content to write.
        """
        resolved = self._resolve(path)
        try:
            resolved.parent.mkdir(parents=True, exist_ok=True)
            resolved.write_text(content)
            lines = content.count("\n") + 1
            return f"Written: {path} ({lines} lines)"
        except Exception as e:
            return f"Error writing {path}: {e}"

    @tool()
    def file_edit(self, path: str, old_text: str, new_text: str) -> str:
        """Replace a specific string in a file.

        Args:
            path: Relative path within the workspace.
            old_text: The exact text to find.
            new_text: The replacement text.
        """
        resolved = self._resolve(path)
        if not resolved.exists():
            return f"Error: file not found: {path}"
        try:
            content = resolved.read_text()
            if old_text not in content:
                return f"Error: text not found in {path}"
            count = content.count(old_text)
            if count > 1:
                return f"Error: text appears {count} times in {path}. Be more specific."
            updated = content.replace(old_text, new_text, 1)
            resolved.write_text(updated)
            return f"Edited: {path}"
        except Exception as e:
            return f"Error editing {path}: {e}"

    @tool()
    def list_dir(self, path: str = ".", max_depth: int = 2) -> str:
        """List files and directories in the workspace.

        Args:
            path: Relative directory path.
            max_depth: Maximum depth to recurse.
        """
        resolved = self._resolve(path)
        if not resolved.exists():
            return f"Error: directory not found: {path}"
        if not resolved.is_dir():
            return f"Error: {path} is a file, not a directory"

        lines: list[str] = []
        self._tree(resolved, resolved, 0, max_depth, lines)
        return "\n".join(lines) if lines else "(empty directory)"

    def _tree(
        self, root: Path, current: Path, depth: int, max_depth: int, lines: list[str]
    ) -> None:
        if depth > max_depth:
            return
        try:
            entries = sorted(current.iterdir(), key=lambda p: (not p.is_dir(), p.name))
        except PermissionError:
            return
        for entry in entries:
            if entry.name.startswith("."):
                continue
            rel = entry.relative_to(root)
            prefix = "  " * depth
            if entry.is_dir():
                lines.append(f"{prefix}{rel}/")
                self._tree(root, entry, depth + 1, max_depth, lines)
            else:
                size = entry.stat().st_size
                lines.append(f"{prefix}{rel}  ({size}B)")
