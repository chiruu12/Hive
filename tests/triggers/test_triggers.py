"""Tests for trigger systems."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from hive.triggers.webhook import WebhookTrigger


class TestWebhookTrigger:
    @pytest.mark.asyncio
    async def test_register_and_list(self) -> None:
        wh = WebhookTrigger()
        tid = wh.register("/test", lambda body: None, name="test-hook")
        triggers = wh.active_triggers
        assert len(triggers) == 1
        assert triggers[0]["path"] == "/test"
        assert triggers[0]["method"] == "POST"
        assert triggers[0]["name"] == "test-hook"
        assert triggers[0]["id"] == tid

    @pytest.mark.asyncio
    async def test_unregister(self) -> None:
        wh = WebhookTrigger()
        tid = wh.register("/test", lambda body: None)
        wh.unregister(tid)
        assert len(wh.active_triggers) == 0

    @pytest.mark.asyncio
    async def test_start_stop(self) -> None:
        wh = WebhookTrigger(port=0)
        await wh.start()
        assert wh._server is not None
        await wh.stop()
        assert wh._server is None

    @pytest.mark.asyncio
    async def test_webhook_fires_callback(self) -> None:
        received: list[str] = []

        def handler(body: str) -> None:
            received.append(body)

        wh = WebhookTrigger(host="127.0.0.1", port=0)
        wh.register("/trigger/test", handler, method="POST")
        await wh.start()

        port = wh._server.sockets[0].getsockname()[1]  # type: ignore[union-attr]

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"http://127.0.0.1:{port}/trigger/test",
                    content='{"action": "go"}',
                    headers={"Content-Type": "application/json"},
                )
                assert resp.status_code == 200
        finally:
            await wh.stop()

        assert len(received) == 1
        assert '"action"' in received[0]

    @pytest.mark.asyncio
    async def test_webhook_async_callback(self) -> None:
        received: list[str] = []

        async def handler(body: str) -> None:
            received.append(body)

        wh = WebhookTrigger(host="127.0.0.1", port=0)
        wh.register("/async", handler, method="POST")
        await wh.start()

        port = wh._server.sockets[0].getsockname()[1]  # type: ignore[union-attr]

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"http://127.0.0.1:{port}/async",
                    content="hello",
                )
                assert resp.status_code == 200
        finally:
            await wh.stop()

        assert received == ["hello"]

    @pytest.mark.asyncio
    async def test_webhook_404_unregistered(self) -> None:
        wh = WebhookTrigger(host="127.0.0.1", port=0)
        await wh.start()

        port = wh._server.sockets[0].getsockname()[1]  # type: ignore[union-attr]

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(f"http://127.0.0.1:{port}/nope")
                assert resp.status_code == 404
        finally:
            await wh.stop()


class TestHotkeyTrigger:
    def test_import_error_without_pynput(self) -> None:
        with patch("hive.triggers.hotkey._HAS_PYNPUT", False):
            from hive.triggers.hotkey import HotkeyTrigger

            with pytest.raises(ImportError, match="pynput"):
                HotkeyTrigger()

    def test_register_and_list(self) -> None:
        mock_keyboard = MagicMock()
        mock_keyboard.Key.cmd = "cmd_key"
        mock_keyboard.Key.shift = "shift_key"
        mock_keyboard.KeyCode.from_char.return_value = "m_key"

        mod_attrs = {
            "cmd": "cmd_key", "ctrl": "ctrl_key",
            "alt": "alt_key", "shift": "shift_key",
        }
        with (
            patch("hive.triggers.hotkey._HAS_PYNPUT", True),
            patch("hive.triggers.hotkey.keyboard", mock_keyboard),
            patch("hive.triggers.hotkey._MODIFIER_ATTRS", mod_attrs),
        ):
            from hive.triggers.hotkey import HotkeyTrigger

            ht = HotkeyTrigger()
            ht.register("cmd+shift+m", lambda: None, name="mic")
            triggers = ht.active_triggers
            assert len(triggers) == 1
            assert triggers[0]["combo"] == "cmd+shift+m"
            assert triggers[0]["name"] == "mic"

    def test_unregister(self) -> None:
        mock_keyboard = MagicMock()
        mock_keyboard.Key.cmd = "cmd_key"
        mock_keyboard.KeyCode.from_char.return_value = "x_key"

        mod_attrs = {
            "cmd": "cmd_key", "ctrl": "ctrl_key",
            "alt": "alt_key", "shift": "shift_key",
        }
        with (
            patch("hive.triggers.hotkey._HAS_PYNPUT", True),
            patch("hive.triggers.hotkey.keyboard", mock_keyboard),
            patch("hive.triggers.hotkey._MODIFIER_ATTRS", mod_attrs),
        ):
            from hive.triggers.hotkey import HotkeyTrigger

            ht = HotkeyTrigger()
            tid = ht.register("cmd+x", lambda: None)
            ht.unregister(tid)
            assert len(ht.active_triggers) == 0
