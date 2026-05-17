"""Shell execution toolkit — sandboxed command execution for agents."""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

from hive.tools.base import Toolkit, tool

logger = logging.getLogger(__name__)


class ShellToolkit(Toolkit):
    """Sandboxed shell execution within a workspace directory.

    Usage:
        tk = ShellToolkit()                           # defaults to CWD
        tk = ShellToolkit(workspace="/my/dir")         # explicit path
        tk = ShellToolkit(restrict=False)              # allow all commands
    """

    ALLOWED_COMMANDS = {
        "ls", "cat", "head", "tail", "grep", "find", "wc", "sort", "uniq",
        "diff", "echo", "printf", "touch", "mkdir", "cp", "mv", "rm",
        "python", "python3", "pip", "uv", "node", "npm", "npx", "git",
        "ruff", "mypy", "pytest", "cargo", "go", "make", "curl", "wget",
        "jq", "sed", "awk", "tr", "cut", "tee", "which", "env", "date",
        "pwd", "cd", "test",
    }

    def __init__(
        self,
        workspace: str | Path | None = None,
        timeout: int = 30,
        restrict: bool = True,
    ):
        self._workspace = Path(workspace).resolve() if workspace else Path.cwd()
        self._workspace.mkdir(parents=True, exist_ok=True)
        self._timeout = timeout
        self._restrict = restrict

    def _check_command(self, command: str) -> str | None:
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
