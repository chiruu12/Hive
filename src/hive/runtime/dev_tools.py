"""Developer toolkits — file, shell, and git access for agents."""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
from pathlib import Path

from hive.runtime.tools import Toolkit, tool

logger = logging.getLogger(__name__)


class FileToolkit(Toolkit):
    """File system access scoped to a workspace directory."""

    def __init__(self, workspace: Path):
        self._workspace = workspace.resolve()
        self._workspace.mkdir(parents=True, exist_ok=True)

    def _resolve(self, path: str) -> Path:
        """Resolve a path within the workspace, preventing escape."""
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


class ShellToolkit(Toolkit):
    """Sandboxed shell execution within a workspace directory."""

    ALLOWED_COMMANDS = {
        "ls",
        "cat",
        "head",
        "tail",
        "grep",
        "find",
        "wc",
        "sort",
        "uniq",
        "diff",
        "echo",
        "printf",
        "touch",
        "mkdir",
        "cp",
        "mv",
        "rm",
        "python",
        "python3",
        "pip",
        "uv",
        "node",
        "npm",
        "npx",
        "git",
        "ruff",
        "mypy",
        "pytest",
        "cargo",
        "go",
        "make",
        "curl",
        "wget",
        "jq",
        "sed",
        "awk",
        "tr",
        "cut",
        "tee",
        "which",
        "env",
        "date",
        "pwd",
        "cd",
        "test",
    }

    def __init__(self, workspace: Path, timeout: int = 30, restrict: bool = True):
        self._workspace = workspace.resolve()
        self._workspace.mkdir(parents=True, exist_ok=True)
        self._timeout = timeout
        self._restrict = restrict

    def _check_command(self, command: str) -> str | None:
        """Return error message if command is blocked, None if allowed."""
        if not self._restrict:
            return None
        first_token = command.strip().split()[0] if command.strip() else ""
        base = first_token.split("/")[-1]
        if base not in self.ALLOWED_COMMANDS:
            return (
                f"Error: command '{base}' not in allowlist. "
                f"Allowed: {', '.join(sorted(self.ALLOWED_COMMANDS)[:20])}..."
            )
        return None

    @tool()
    async def shell_exec(self, command: str) -> str:
        """Execute a shell command in the workspace directory.

        Args:
            command: The shell command to run.
        """
        rejection = self._check_command(command)
        if rejection:
            return rejection

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self._workspace),
                env={**os.environ, "HOME": str(self._workspace)},
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=self._timeout)
            output = stdout.decode(errors="replace")
            err = stderr.decode(errors="replace")
            result_parts = []
            if output.strip():
                result_parts.append(output.strip()[:5000])
            if err.strip():
                result_parts.append(f"STDERR:\n{err.strip()[:2000]}")
            result_parts.append(f"(exit code: {proc.returncode})")
            return "\n".join(result_parts)
        except TimeoutError:
            return f"Error: command timed out after {self._timeout}s"
        except Exception as e:
            return f"Error executing command: {e}"


class GitToolkit(Toolkit):
    """Git operations within a workspace."""

    def __init__(self, workspace: Path):
        self._workspace = workspace.resolve()
        self._workspace.mkdir(parents=True, exist_ok=True)

    def _run_git(self, *args: str) -> str:
        try:
            result = subprocess.run(
                ["git", *args],
                cwd=str(self._workspace),
                capture_output=True,
                text=True,
                timeout=30,
            )
            output = result.stdout.strip()
            if result.returncode != 0:
                err = result.stderr.strip()
                return f"Error (exit {result.returncode}): {err or output}"
            return output or "(no output)"
        except FileNotFoundError:
            return "Error: git is not installed"
        except subprocess.TimeoutExpired:
            return "Error: git command timed out"
        except Exception as e:
            return f"Error: {e}"

    @tool()
    def git_status(self) -> str:
        """Show the working tree status."""
        return self._run_git("status", "--short")

    @tool()
    def git_diff(self, staged: bool = False) -> str:
        """Show changes in the working directory.

        Args:
            staged: If true, show staged changes instead of unstaged.
        """
        args = ["diff"]
        if staged:
            args.append("--cached")
        return self._run_git(*args)

    @tool()
    def git_log(self, count: int = 10) -> str:
        """Show recent commit history.

        Args:
            count: Number of commits to show.
        """
        return self._run_git("log", "--oneline", f"-{count}")

    @tool()
    def git_add(self, path: str = ".") -> str:
        """Stage files for commit.

        Args:
            path: File or directory to stage.
        """
        return self._run_git("add", path)

    @tool()
    def git_commit(self, message: str) -> str:
        """Create a commit with the given message.

        Args:
            message: Commit message.
        """
        return self._run_git("commit", "-m", message)

    @tool()
    def git_init(self) -> str:
        """Initialize a new git repository in the workspace."""
        return self._run_git("init")
