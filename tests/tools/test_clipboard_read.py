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
