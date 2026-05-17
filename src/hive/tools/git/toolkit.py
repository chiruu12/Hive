"""Git operations toolkit — version control for agents."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from hive.tools.base import Toolkit, tool

logger = logging.getLogger(__name__)


class GitToolkit(Toolkit):
    """Git operations within a workspace.

    Usage:
        tk = GitToolkit()                      # defaults to CWD
        tk = GitToolkit(workspace="/my/repo")   # explicit path
    """

    def __init__(self, workspace: str | Path | None = None):
        self._workspace = Path(workspace).resolve() if workspace else Path.cwd()
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
