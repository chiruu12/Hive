"""Tests for developer toolkits — file, shell, and git access."""

from __future__ import annotations

from pathlib import Path

import pytest

from hive.runtime.dev_tools import FileToolkit, GitToolkit, ShellToolkit


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
        result = await st.shell_exec("true")
        assert "exit code: 0" in result

    @pytest.mark.asyncio
    async def test_stderr(self, st: ShellToolkit) -> None:
        result = await st.shell_exec("echo err >&2")
        assert "err" in result

    @pytest.mark.asyncio
    async def test_blocked_command(self, st: ShellToolkit) -> None:
        result = await st.shell_exec("sudo rm -rf /")
        assert "blocked" in result.lower()

    @pytest.mark.asyncio
    async def test_timeout(self, tmp_path: Path) -> None:
        st = ShellToolkit(tmp_path, timeout=1)
        result = await st.shell_exec("sleep 10")
        assert "timed out" in result


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
