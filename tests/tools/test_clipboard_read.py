"""Tests for ClipboardToolkit.read_clipboard."""

from __future__ import annotations

import pytest

from hive.tools.clipboard import toolkit as cb


@pytest.mark.asyncio
async def test_read_clipboard_returns_trimmed_text(monkeypatch):
    async def fake() -> str:
        return "  https://example.com  \n"

    monkeypatch.setattr(cb, "_read_from_system_clipboard", fake)
    tk = cb.ClipboardToolkit()
    assert await tk.read_clipboard() == "https://example.com"


@pytest.mark.asyncio
async def test_read_clipboard_empty(monkeypatch):
    async def fake() -> str:
        return "   \n"

    monkeypatch.setattr(cb, "_read_from_system_clipboard", fake)
    tk = cb.ClipboardToolkit()
    assert "empty" in (await tk.read_clipboard()).lower()


@pytest.mark.asyncio
async def test_read_clipboard_unavailable(monkeypatch):
    async def fake() -> None:
        return None

    monkeypatch.setattr(cb, "_read_from_system_clipboard", fake)
    tk = cb.ClipboardToolkit()
    assert "couldn't read" in (await tk.read_clipboard()).lower()


@pytest.mark.asyncio
async def test_read_clipboard_exposed_as_tool() -> None:
    tk = cb.ClipboardToolkit()
    tk.bind("agent")
    assert "read_clipboard" in {t.name for t in tk.get_tools()}


@pytest.mark.asyncio
async def test_helper_unsupported_platform(monkeypatch):
    monkeypatch.setattr(cb.platform, "system", lambda: "Windows")
    assert await cb._read_from_system_clipboard() is None


class _FakeProc:
    def __init__(self, returncode: int, stdout: bytes) -> None:
        self.returncode = returncode
        self._stdout = stdout

    async def communicate(self):
        return self._stdout, b""


@pytest.mark.asyncio
async def test_helper_reads_subprocess_stdout(monkeypatch):
    """The macOS/Linux path returns decoded stdout when the command succeeds."""
    monkeypatch.setattr(cb.platform, "system", lambda: "Darwin")

    async def fake_exec(*cmd, **kwargs):
        return _FakeProc(0, b"copied text\n")

    monkeypatch.setattr(cb.asyncio, "create_subprocess_exec", fake_exec)
    assert await cb._read_from_system_clipboard() == "copied text\n"


@pytest.mark.asyncio
async def test_helper_nonzero_returncode_is_none(monkeypatch):
    """A failed clipboard command yields None (never raises)."""
    monkeypatch.setattr(cb.platform, "system", lambda: "Linux")

    async def fake_exec(*cmd, **kwargs):
        return _FakeProc(1, b"")

    monkeypatch.setattr(cb.asyncio, "create_subprocess_exec", fake_exec)
    assert await cb._read_from_system_clipboard() is None
