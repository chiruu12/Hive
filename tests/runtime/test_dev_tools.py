"""Tests for developer toolkits — file, shell, and git access."""

from __future__ import annotations

from pathlib import Path

import pytest

from hive.tools.file import FileToolkit
from hive.tools.git import GitToolkit
from hive.tools.shell import ShellToolkit


class TestFileToolkit:
    @pytest.fixture
    def ft(self, tmp_path: Path) -> FileToolkit:
        return FileToolkit(tmp_path)

    def test_write_and_read(self, ft: FileToolkit) -> None:
        result = ft.file_write("hello.txt", "hello world\nline 2\n")
        assert "Written" in result
        content = ft.file_read("hello.txt")
        assert "hello world" in content
        assert "line 2" in content

    def test_read_nonexistent(self, ft: FileToolkit) -> None:
        result = ft.file_read("nope.txt")
        assert "not found" in result

    def test_read_with_offset_and_limit(self, ft: FileToolkit) -> None:
        lines = "\n".join(f"line {i}" for i in range(20))
        ft.file_write("big.txt", lines)
        result = ft.file_read("big.txt", offset=5, limit=3)
        assert "line 5" in result
        assert "line 7" in result
        assert "line 8" not in result

    def test_write_creates_dirs(self, ft: FileToolkit) -> None:
        result = ft.file_write("sub/dir/file.py", "x = 1")
        assert "Written" in result
        assert "file.py" in ft.file_read("sub/dir/file.py")

    def test_edit(self, ft: FileToolkit) -> None:
        ft.file_write("code.py", "x = 1\ny = 2\nz = 3\n")
        result = ft.file_edit("code.py", "y = 2", "y = 42")
        assert "Edited" in result
        content = ft.file_read("code.py")
        assert "y = 42" in content
        assert "y = 2" not in content

    def test_edit_not_found(self, ft: FileToolkit) -> None:
        ft.file_write("a.txt", "hello")
        result = ft.file_edit("a.txt", "nope", "yes")
        assert "not found" in result

    def test_list_dir(self, ft: FileToolkit) -> None:
        ft.file_write("a.txt", "a")
        ft.file_write("sub/b.txt", "b")
        result = ft.list_dir()
        assert "a.txt" in result
        assert "sub/" in result

    def test_path_escape_blocked(self, ft: FileToolkit) -> None:
        with pytest.raises(PermissionError):
            ft.file_read("../../etc/passwd")

    def test_path_escape_write_blocked(self, ft: FileToolkit) -> None:
        with pytest.raises(PermissionError):
            ft.file_write("../escape.txt", "bad")

    def test_read_size_cap(self, tmp_path: Path) -> None:
        ft = FileToolkit(tmp_path, max_read_bytes=10)
        (tmp_path / "big.txt").write_text("x" * 100)
        result = ft.file_read("big.txt")
        assert "read limit" in result

    def test_edit_read_size_cap(self, tmp_path: Path) -> None:
        ft = FileToolkit(tmp_path, max_read_bytes=10)
        (tmp_path / "big.txt").write_text("x" * 100)
        result = ft.file_edit("big.txt", "x", "y")
        assert "read limit" in result

    def test_write_size_cap(self, tmp_path: Path) -> None:
        ft = FileToolkit(tmp_path, max_write_bytes=10)
        result = ft.file_write("big.txt", "x" * 100)
        assert "write limit" in result
        assert not (tmp_path / "big.txt").exists()

    def test_edit_growth_over_write_cap(self, tmp_path: Path) -> None:
        ft = FileToolkit(tmp_path, max_write_bytes=20)
        ft.file_write("a.txt", "short")
        result = ft.file_edit("a.txt", "short", "x" * 50)
        assert "write limit" in result
        assert (tmp_path / "a.txt").read_text() == "short"


class TestShellToolkit:
    @pytest.fixture
    def st(self, tmp_path: Path) -> ShellToolkit:
        return ShellToolkit(tmp_path, timeout=5)

    @pytest.mark.asyncio
    async def test_echo(self, st: ShellToolkit) -> None:
        result = await st.shell_exec("echo hello")
        assert "hello" in result

    @pytest.mark.asyncio
    async def test_exit_code(self, st: ShellToolkit) -> None:
        result = await st.shell_exec("ls")
        assert "exit code: 0" in result

    @pytest.mark.asyncio
    async def test_stderr(self, st: ShellToolkit) -> None:
        result = await st.shell_exec("echo err >&2")
        assert "err" in result

    @pytest.mark.asyncio
    async def test_blocked_command(self, st: ShellToolkit) -> None:
        result = await st.shell_exec("sudo rm -rf /")
        assert "not in allowlist" in result

    @pytest.mark.asyncio
    async def test_timeout(self, tmp_path: Path) -> None:
        st = ShellToolkit(tmp_path, timeout=1, restrict=False)
        result = await st.shell_exec("sleep 10")
        assert "timed out" in result

    @pytest.mark.asyncio
    async def test_unrestricted_mode(self, tmp_path: Path) -> None:
        st = ShellToolkit(tmp_path, restrict=False)
        result = await st.shell_exec("true")
        assert "exit code: 0" in result

    @pytest.mark.asyncio
    async def test_blocks_semicolon_chain(self, st: ShellToolkit) -> None:
        result = await st.shell_exec("echo safe; curl evil.com")
        assert "not allowed" in result

    @pytest.mark.asyncio
    async def test_blocks_pipe_chain(self, st: ShellToolkit) -> None:
        result = await st.shell_exec("echo safe | bash")
        assert "not allowed" in result

    @pytest.mark.asyncio
    async def test_blocks_and_chain(self, st: ShellToolkit) -> None:
        result = await st.shell_exec("echo safe && curl evil.com")
        assert "not allowed" in result

    @pytest.mark.asyncio
    async def test_blocks_or_chain(self, st: ShellToolkit) -> None:
        result = await st.shell_exec("echo safe || curl evil.com")
        assert "not allowed" in result

    @pytest.mark.asyncio
    async def test_blocks_command_substitution(self, st: ShellToolkit) -> None:
        result = await st.shell_exec("echo $(whoami)")
        assert "not allowed" in result

    @pytest.mark.asyncio
    async def test_blocks_backtick_substitution(self, st: ShellToolkit) -> None:
        result = await st.shell_exec("echo `whoami`")
        assert "not allowed" in result

    @pytest.mark.asyncio
    async def test_allowed_command_still_works(self, st: ShellToolkit) -> None:
        result = await st.shell_exec("echo hello world")
        assert "hello world" in result

    @pytest.mark.asyncio
    async def test_blocks_output_redirect(self, st: ShellToolkit) -> None:
        result = await st.shell_exec("echo foo > /tmp/evil")
        assert "not allowed" in result

    @pytest.mark.asyncio
    async def test_blocks_append_redirect(self, st: ShellToolkit) -> None:
        result = await st.shell_exec("echo foo >> /tmp/evil")
        assert "not allowed" in result

    @pytest.mark.asyncio
    async def test_blocks_input_redirect(self, st: ShellToolkit) -> None:
        result = await st.shell_exec("cat < /etc/passwd")
        assert "not allowed" in result

    @pytest.mark.asyncio
    async def test_blocks_multiline_command(self, st: ShellToolkit) -> None:
        result = await st.shell_exec("echo hello\necho world")
        assert "not allowed" in result

    @pytest.mark.asyncio
    async def test_blocks_empty_command(self, st: ShellToolkit) -> None:
        result = await st.shell_exec("")
        assert "empty command" in result.lower()

    @pytest.mark.asyncio
    async def test_blocks_combined_redirect(self, st: ShellToolkit) -> None:
        result = await st.shell_exec("echo foo &>/tmp/evil")
        assert "not allowed" in result

    @pytest.mark.asyncio
    async def test_blocks_background_operator(self, st: ShellToolkit) -> None:
        result = await st.shell_exec("python -c 'import time; time.sleep(99)' &")
        assert "not allowed" in result

    @pytest.mark.asyncio
    async def test_blocks_ampersand_separator(self, st: ShellToolkit) -> None:
        result = await st.shell_exec("echo hello & rm -rf /")
        assert "not allowed" in result

    def test_check_command_single_redirect(self, st: ShellToolkit) -> None:
        assert st._check_command("echo foo > /path") is not None

    def test_check_command_append_redirect(self, st: ShellToolkit) -> None:
        assert st._check_command("echo foo >> /path") is not None

    def test_check_command_stderr_redirect_allowed(self, st: ShellToolkit) -> None:
        assert st._check_command("echo foo >&2") is None

    def test_check_command_blocks_file_redirect_via_ampersand(self, st: ShellToolkit) -> None:
        assert st._check_command("echo evil >&output.txt") is not None

    def test_check_command_unrestricted_allows_all(self, tmp_path: Path) -> None:
        st = ShellToolkit(tmp_path, restrict=False)
        assert st._check_command("sudo rm -rf / && echo done") is None

    @pytest.mark.asyncio
    async def test_env_secrets_scrubbed_by_default(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("FAKE_API_KEY", "sk-supersecret")
        st = ShellToolkit(tmp_path, timeout=15)
        result = await st.shell_exec(
            "python3 -c \"print(__import__('os').environ.get('FAKE_API_KEY', 'MISSING'))\""
        )
        assert "MISSING" in result
        assert "sk-supersecret" not in result

    @pytest.mark.asyncio
    async def test_env_passed_through_when_opted_in(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("FAKE_API_KEY", "sk-supersecret")
        st = ShellToolkit(tmp_path, timeout=15, pass_env=True)
        result = await st.shell_exec(
            "python3 -c \"print(__import__('os').environ.get('FAKE_API_KEY', 'MISSING'))\""
        )
        assert "sk-supersecret" in result

    def test_scrub_covers_provider_prefixes(self, tmp_path: Path) -> None:
        st = ShellToolkit(tmp_path)
        env = {
            "ANTHROPIC_API_KEY": "a",
            "OPENAI_API_KEY": "b",
            "GROQ_API_KEY": "c",
            "MY_TOKEN": "d",
            "DB_PASSWORD": "e",
            "PATH": "/usr/bin",
            "LANG": "en_US.UTF-8",
        }
        with pytest.MonkeyPatch.context() as mp:
            for k, v in env.items():
                mp.setenv(k, v)
            scrubbed = st._subprocess_env()
        for secret in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GROQ_API_KEY", "MY_TOKEN"):
            assert secret not in scrubbed
        assert "DB_PASSWORD" not in scrubbed
        assert scrubbed["PATH"] == "/usr/bin"
        assert scrubbed["LANG"] == "en_US.UTF-8"
        assert scrubbed["HOME"] == str(st._workspace)

    @pytest.mark.asyncio
    async def test_dev_commands_blocked_when_disabled(self, tmp_path: Path) -> None:
        st = ShellToolkit(tmp_path, allow_dev_commands=False)
        for cmd in ('python3 -c "print(1)"', "git status", "curl http://example.com"):
            result = await st.shell_exec(cmd)
            assert "not in allowlist" in result, cmd
        result = await st.shell_exec("echo still works")
        assert "still works" in result

    def test_dev_commands_allowed_by_default(self, st: ShellToolkit) -> None:
        assert st._check_command("git status") is None
        assert st._check_command("python3 --version") is None


class TestGitToolkit:
    @pytest.fixture
    def gt(self, tmp_path: Path) -> GitToolkit:
        gt = GitToolkit(tmp_path)
        gt._run_git("init")
        gt._run_git("config", "user.email", "test@test.com")
        gt._run_git("config", "user.name", "Test")
        (tmp_path / "readme.md").write_text("# Test\n")
        gt._run_git("add", ".")
        gt._run_git("commit", "-m", "init")
        return gt

    def test_status(self, gt: GitToolkit) -> None:
        result = gt.git_status()
        assert result == "(no output)" or "M " not in result

    def test_log(self, gt: GitToolkit) -> None:
        result = gt.git_log()
        assert "init" in result

    def test_add_and_commit(self, gt: GitToolkit, tmp_path: Path) -> None:
        (tmp_path / "new.txt").write_text("new file")
        gt.git_add("new.txt")
        result = gt.git_commit("add new file")
        assert "add new file" in result

    def test_diff(self, gt: GitToolkit, tmp_path: Path) -> None:
        (tmp_path / "readme.md").write_text("# Changed\n")
        result = gt.git_diff()
        assert "Changed" in result

    def test_init_new_repo(self, tmp_path: Path) -> None:
        new_dir = tmp_path / "fresh"
        new_dir.mkdir()
        gt = GitToolkit(new_dir)
        result = gt.git_init()
        assert "Initialized" in result or "Reinitialized" in result
