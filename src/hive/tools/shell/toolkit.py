"""Shell execution toolkit — sandboxed command execution for agents."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shlex
from pathlib import Path

from hive.tools._env import scrub_secrets_from_env
from hive.tools._process import kill_and_reap
from hive.tools.base import Toolkit, tool

logger = logging.getLogger(__name__)


class ShellToolkit(Toolkit):
    """Sandboxed shell execution within a workspace directory.

    Usage:
        tk = ShellToolkit()                            # defaults to CWD
        tk = ShellToolkit(workspace="/my/dir")          # explicit path
        tk = ShellToolkit(restrict=False)               # allow all commands
        tk = ShellToolkit(allow_dev_commands=False)     # file/text utilities only

    Note: dev commands (``python``, ``git``, ``curl``, etc.) are disabled by
    default. Enable ``allow_dev_commands=True`` only for trusted agents -- those
    tools can escape the workspace jail. Run inside a container when the agent
    is untrusted.
    """

    # File/text utilities that stay inside the workspace.
    SAFE_COMMANDS = {
        "ls",
        "cat",
        "head",
        "tail",
        "grep",
        # find omitted: -exec/-delete bypass shell-operator blocking (RCE) and
        # path args are hard to jail safely; use ls/grep in restricted mode.
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
        allow_dev_commands: bool = False,
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

    # Commands that accept file paths and should be workspace-restricted.
    _FILE_PATH_COMMANDS = {
        "cat",
        "head",
        "tail",
        "grep",
        "touch",
        "mkdir",
        "cp",
        "mv",
        "rm",
        "sort",
        "cut",
        "uniq",
        "diff",
        "wc",
        "ls",
        "jq",
    }

    # Flags whose next token is a value, not a path (per-command).
    _CUT_VALUE_FLAGS = frozenset(
        {"-d", "-f", "-c", "-b", "--delimiter", "--fields", "--bytes", "--characters"}
    )
    _DIFF_VALUE_FLAGS = frozenset(
        {
            "-C",
            "-U",
            "-W",
            "-L",
            "--label",
            "--ifdef",
            "--horizon-lines",
            "--new-group-format",
            "--old-group-format",
            "--unchanged-group-format",
            "--line-format",
            "--LTYPE",
        }
    )
    _SORT_TEMP_FLAGS = frozenset({"-T", "--temporary-directory"})
    _SORT_PATH_FLAGS = frozenset({"-o", "--output"})
    _TEST_UNARY_PATH_FLAGS = frozenset(
        {
            "-a",
            "-b",
            "-c",
            "-d",
            "-e",
            "-f",
            "-g",
            "-h",
            "-k",
            "-p",
            "-r",
            "-s",
            "-t",
            "-u",
            "-w",
            "-x",
            "-z",
            "-G",
            "-L",
            "-N",
            "-O",
            "-S",
        }
    )
    _TEST_BINARY_PATH_OPS = frozenset({"-nt", "-ot", "-ef"})
    _SORT_FORBIDDEN_FLAGS: dict[str, str] = {
        "--files0-from": (
            "Error: sort '--files0-from' not allowed in restricted mode "
            "(NUL-separated list can reference paths outside workspace)"
        ),
        "--compress-program": (
            "Error: sort '--compress-program' not allowed in restricted mode "
            "(executes arbitrary programs)"
        ),
    }
    _GREP_PATH_FLAGS = frozenset({"-f", "--file", "--exclude-from"})
    _JQ_PATH_FLAGS = frozenset({"-L", "--library-path", "-f", "--from-file"})
    _JQ_SKIP_FLAGS = frozenset(
        {
            "--arg",
            "--argjson",
            "--args",
            "--jsonargs",
            "--slurpfile",
            "--rawfile",
        }
    )
    _PATH_EXPANSION_RE = re.compile(r"[~$`%]")

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

        parts, token_error = self._tokenize_command(cmd)
        if token_error:
            return token_error
        assert parts is not None

        first_token = parts[0] if parts else ""
        base = first_token.split("/")[-1]
        if base not in self._allowed:
            return (
                f"Error: command '{base}' not in allowlist. "
                f"Allowed: {', '.join(sorted(self._allowed)[:20])}..."
            )

        if base == "test":
            path_error = self._check_test_paths(parts)
            if path_error:
                return path_error

        # Path containment: commands that read/write files must stay in workspace
        if base in self._FILE_PATH_COMMANDS:
            if base == "sort":
                sort_flag_error = self._check_sort_restricted_flags(parts)
                if sort_flag_error:
                    return sort_flag_error
            path_error = self._check_paths_in_command(base, parts)
            if path_error:
                return path_error

        return None

    def _tokenize_command(self, cmd: str) -> tuple[list[str] | None, str | None]:
        """Parse a command the way the shell will, stripping quotes from tokens."""
        try:
            parts = shlex.split(cmd, posix=True)
        except ValueError as exc:
            return None, f"Error: invalid command quoting: {exc}"
        if not parts:
            return None, "Error: empty command"
        return parts, None

    @staticmethod
    def _match_flag_with_value(
        token: str,
        value_flags: frozenset[str],
    ) -> tuple[str, str | None] | None:
        """Match a flag token and any attached value (``-oPATH``, ``--output=PATH``)."""
        if "=" in token:
            flag, attached = token.split("=", 1)
            if flag in value_flags:
                return flag, attached
            return None

        if token in value_flags:
            return token, None

        if token.startswith("-") and not token.startswith("--") and len(token) > 2:
            for flag in value_flags:
                if flag.startswith("--") or len(flag) != 2:
                    continue
                if token.startswith(flag) and len(token) > len(flag):
                    return flag, token[len(flag) :]
        return None

    def _check_sort_restricted_flags(self, parts: list[str]) -> str | None:
        """Reject sort flags that bypass the workspace jail or enable RCE.

        Matches exact flags and unambiguous long-option prefixes (GNU/BSD
        ``sort`` accepts ``--files0`` as ``--files0-from``, etc.).
        """
        i = 1
        while i < len(parts):
            token = parts[i]
            if not token.startswith("-"):
                i += 1
                continue
            flag = token.split("=", 1)[0]
            for forbidden, message in self._SORT_FORBIDDEN_FLAGS.items():
                if flag == forbidden or (
                    flag.startswith("--") and len(flag) > 2 and forbidden.startswith(flag)
                ):
                    return message
            i += 1
        return None

    def _check_paths_in_command(self, base: str, parts: list[str]) -> str | None:
        """Validate that file paths in the command stay within the workspace."""
        path_args = self._extract_path_args(base, parts)

        for arg in path_args:
            path_error = self._validate_path_containment(arg)
            if path_error:
                return path_error

        return None

    def _validate_path_containment(self, arg: str) -> str | None:
        """Reject shell expansion in path tokens and enforce workspace jail."""
        if self._PATH_EXPANSION_RE.search(arg):
            return (
                f"Error: path '{arg}' uses shell expansion (~, $, `, %); "
                "use workspace-relative paths like 'foo' or './foo'"
            )
        try:
            resolved = (self._workspace / arg).resolve()
            if not resolved.is_relative_to(self._workspace.resolve()):
                return f"Error: path '{arg}' escapes workspace"
        except (ValueError, OSError):
            # Invalid path — let the command handle it
            pass
        return None

    def _extract_path_args(self, base: str, parts: list[str]) -> list[str]:
        """Return positional path arguments from a tokenized command."""
        if base == "grep":
            return self._grep_path_args(parts)
        if base == "cut":
            return self._cut_path_args(parts)
        if base == "diff":
            return self._flagged_path_args(parts, self._DIFF_VALUE_FLAGS)
        if base == "sort":
            return self._flagged_path_args(
                parts,
                path_value_flags=self._SORT_PATH_FLAGS | self._SORT_TEMP_FLAGS,
            )
        if base == "jq":
            return self._jq_path_args(parts)
        if base in {"uniq", "wc", "ls", "cat", "head", "tail", "touch", "mkdir", "cp", "mv", "rm"}:
            return self._simple_path_args(parts)
        return []

    def _grep_path_args(self, parts: list[str]) -> list[str]:
        # grep [flags] pattern [file...]; -f/--file/--exclude-from values are paths
        paths: list[str] = []
        found_pattern = False
        i = 1
        while i < len(parts):
            token = parts[i]
            if token.startswith("-"):
                matched = self._match_flag_with_value(token, self._GREP_PATH_FLAGS)
                if matched is not None:
                    flag, attached = matched
                    if attached is not None:
                        paths.append(attached)
                        i += 1
                    elif i + 1 < len(parts):
                        paths.append(parts[i + 1])
                        i += 2
                    else:
                        i += 1
                    continue
                i += 1
                continue
            if not found_pattern:
                found_pattern = True
                i += 1
                continue
            paths.append(token)
            i += 1
        return paths

    def _cut_path_args(self, parts: list[str]) -> list[str]:
        paths: list[str] = []
        i = 1
        while i < len(parts):
            token = parts[i]
            if not token.startswith("-"):
                paths.append(token)
                i += 1
                continue

            flag = token.split("=", 1)[0]
            if flag in self._CUT_VALUE_FLAGS:
                if "=" in token:
                    i += 1
                else:
                    i += 2
                continue

            # Attached short-flag values, e.g. cut -d: -f1
            if len(token) > 2 and not token.startswith("--"):
                i += 1
                continue

            i += 1
        return paths

    def _simple_path_args(self, parts: list[str]) -> list[str]:
        return [token for token in parts[1:] if not token.startswith("-")]

    def _flagged_path_args(
        self,
        parts: list[str],
        skip_value_flags: frozenset[str] = frozenset(),
        *,
        path_value_flags: frozenset[str] | None = None,
    ) -> list[str]:
        path_value_flags = path_value_flags or frozenset()
        paths: list[str] = []
        i = 1
        while i < len(parts):
            token = parts[i]
            if not token.startswith("-"):
                paths.append(token)
                i += 1
                continue

            skip_match = self._match_flag_with_value(token, skip_value_flags)
            if skip_match is not None:
                _, attached = skip_match
                if attached is not None:
                    i += 1
                elif i + 1 < len(parts):
                    i += 2
                else:
                    i += 1
                continue

            path_match = self._match_flag_with_value(token, path_value_flags)
            if path_match is not None:
                _, attached = path_match
                if attached is not None:
                    paths.append(attached)
                    i += 1
                elif i + 1 < len(parts):
                    paths.append(parts[i + 1])
                    i += 2
                else:
                    i += 1
                continue

            # Inline numeric suffix, e.g. diff -C3, sort -k2
            if len(token) > 2 and not token.startswith("--") and token[1].isalpha():
                i += 1
                continue

            i += 1
        return paths

    def _jq_path_args(self, parts: list[str]) -> list[str]:
        paths: list[str] = []
        i = 1
        while i < len(parts):
            token = parts[i]
            if not token.startswith("-"):
                paths.append(token)
                i += 1
                continue

            path_match = self._match_flag_with_value(token, self._JQ_PATH_FLAGS)
            if path_match is not None:
                _, attached = path_match
                if attached is not None:
                    paths.append(attached)
                    i += 1
                elif i + 1 < len(parts):
                    paths.append(parts[i + 1])
                    i += 2
                else:
                    i += 1
                continue

            flag = token.split("=", 1)[0]
            if flag in self._JQ_SKIP_FLAGS:
                if flag in {"--slurpfile", "--rawfile"}:
                    if "=" in token:
                        i += 1
                    elif i + 2 < len(parts):
                        paths.append(parts[i + 2])
                        i += 3
                    else:
                        i += 1
                    continue
                if "=" in token:
                    i += 1
                else:
                    i += 2
                continue

            i += 1
        return paths

    def _workspace_tmp_dir(self) -> Path:
        tmp = self._workspace / ".hive" / "tmp"
        tmp.mkdir(parents=True, exist_ok=True)
        return tmp

    def _check_test_paths(self, parts: list[str]) -> str | None:
        """Block ``test -f /etc/passwd`` style filesystem existence oracles."""
        paths: list[str] = []
        i = 1
        while i < len(parts):
            token = parts[i]
            if token in self._TEST_BINARY_PATH_OPS:
                if i >= 2 and not parts[i - 1].startswith("-"):
                    paths.append(parts[i - 1])
                if i + 1 < len(parts):
                    paths.append(parts[i + 1])
                    i += 2
                else:
                    i += 1
                continue
            if token in self._TEST_UNARY_PATH_FLAGS:
                if i + 1 < len(parts):
                    paths.append(parts[i + 1])
                    i += 2
                else:
                    i += 1
                continue
            if token.startswith("-"):
                i += 1
                continue
            i += 1
        for arg in paths:
            path_error = self._validate_path_containment(arg)
            if path_error:
                return path_error
        return None

    def _subprocess_env(self) -> dict[str, str]:
        """Environment for agent-run commands.

        By default credential-looking keys (API keys, tokens, secrets, provider
        prefixes) are scrubbed so an agent cannot read them via ``env`` or pass
        them on; ``pass_env=True`` restores full inheritance.
        """
        if self._pass_env:
            env = dict(os.environ)
            env["HOME"] = str(self._workspace)
            tmp_dir = self._workspace_tmp_dir()
            env["TMPDIR"] = str(tmp_dir)
            env["TEMP"] = str(tmp_dir)
            env["TMP"] = str(tmp_dir)
            return env
        return scrub_secrets_from_env(
            workspace=str(self._workspace),
            tmp_dir=str(self._workspace_tmp_dir()),
        )

    @tool(requires_approval=True)
    async def shell_exec(self, command: str) -> str:
        """Execute a shell command in the workspace directory.

        Args:
            command: The shell command to run.
        """
        rejection = self._check_command(command)
        if rejection:
            return rejection

        proc = None
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
            await kill_and_reap(proc)
            return f"Error: command timed out after {self._timeout}s"
        except Exception as e:
            await kill_and_reap(proc)
            return f"Error executing command: {e}"
