"""Shell execution toolkit — sandboxed command execution for agents."""

from __future__ import annotations

import asyncio
import logging
import os
import re
from pathlib import Path

from hive.tools.base import Toolkit, tool

logger = logging.getLogger(__name__)

# Environment keys never passed to agent-run subprocesses unless pass_env=True:
# anything that looks like a credential, plus known provider/cloud prefixes.
_SECRET_ENV = re.compile(
    r"(_API_KEY|_TOKEN|_SECRET|_PASSWORD|_CREDENTIALS)$"
    r"|^(ANTHROPIC|OPENAI|GROQ|FIREWORKS|OPENROUTER|DEEPGRAM|AWS|AZURE|GOOGLE)_"
)


class ShellToolkit(Toolkit):
    """Sandboxed shell execution within a workspace directory.

    Usage:
        tk = ShellToolkit()                            # defaults to CWD
        tk = ShellToolkit(workspace="/my/dir")          # explicit path
        tk = ShellToolkit(restrict=False)               # allow all commands
        tk = ShellToolkit(allow_dev_commands=False)     # file/text utilities only

    Note: with dev commands enabled (the default), the workspace jail is
    advisory, not a security boundary -- interpreters like ``python`` and tools
    like ``git`` can reach outside the workspace. Disable dev commands or run
    inside a container when the agent is untrusted.
    """

    # File/text utilities that stay inside the workspace.
    SAFE_COMMANDS = {
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
        "jq",
        "tr",
        "cut",
        "which",
        "date",
        "pwd",
        "cd",
        "test",
    }

    # Interpreters, package managers, VCS, and network tools. Any of these can
    # escape the workspace jail (``python -c``, ``git config core.pager``,
    # ``curl``), so they form a separate tier gated by ``allow_dev_commands``.
    DEV_COMMANDS = {
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
        "sed",
        "awk",
        "tee",
        "env",
    }

    # Full set, kept for backward compatibility with callers that introspect it.
    ALLOWED_COMMANDS = SAFE_COMMANDS | DEV_COMMANDS

    def __init__(
        self,
        workspace: str | Path | None = None,
        timeout: int = 30,
        restrict: bool = True,
        allow_dev_commands: bool = True,
        pass_env: bool = False,
    ):
        self._workspace = Path(workspace).resolve() if workspace else Path.cwd()
        self._workspace.mkdir(parents=True, exist_ok=True)
        self._timeout = timeout
        self._restrict = restrict
        self._allowed = (
            self.SAFE_COMMANDS | self.DEV_COMMANDS
            if allow_dev_commands
            else set(self.SAFE_COMMANDS)
        )
        self._pass_env = pass_env

    SHELL_OPERATORS = ("&&", "||", "$(", ";", "|", "`", ">>", "&>", "<")

    def _check_command(self, command: str) -> str | None:
        if not self._restrict:
            return None
        cmd = command.strip()
        if not cmd:
            return "Error: empty command"

        for op in self.SHELL_OPERATORS:
            if op in cmd:
                return f"Error: shell operator '{op}' not allowed in restricted mode"

        if re.search(r"(?<![>&])>(?![>&])", cmd):
            return "Error: output redirect '>' not allowed in restricted mode"

        if re.search(r">&(?!\d)", cmd):
            return "Error: output redirect '>&' not allowed in restricted mode"

        if re.search(r"(?<![>&])&(?![>&])", cmd):
            return "Error: background operator '&' not allowed in restricted mode"

        if "\n" in cmd or "\\n" in cmd:
            return "Error: multi-line commands not allowed in restricted mode"

        first_token = cmd.split()[0] if cmd else ""
        base = first_token.split("/")[-1]
        if base not in self._allowed:
            return (
                f"Error: command '{base}' not in allowlist. "
                f"Allowed: {', '.join(sorted(self._allowed)[:20])}..."
            )
        return None

    def _subprocess_env(self) -> dict[str, str]:
        """Environment for agent-run commands.

        By default credential-looking keys (API keys, tokens, secrets, provider
        prefixes) are scrubbed so an agent cannot read them via ``env`` or pass
        them on; ``pass_env=True`` restores full inheritance.
        """
        if self._pass_env:
            env = dict(os.environ)
        else:
            env = {k: v for k, v in os.environ.items() if not _SECRET_ENV.search(k)}
        env["HOME"] = str(self._workspace)
        return env

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
                env=self._subprocess_env(),
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
