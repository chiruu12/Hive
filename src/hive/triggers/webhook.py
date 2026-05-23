"""Lightweight webhook trigger using asyncio."""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import uuid
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)


class WebhookTrigger:
    """HTTP webhook trigger using stdlib asyncio server."""

    def __init__(self, host: str = "127.0.0.1", port: int = 8421) -> None:
        self._host = host
        self._port = port
        self._routes: dict[str, dict[str, Any]] = {}
        self._server: asyncio.Server | None = None

    def register(
        self, path: str, callback: Callable[..., object], method: str = "POST", name: str = ""
    ) -> str:
        trigger_id = str(uuid.uuid4())
        key = f"{method.upper()}:{path}"
        self._routes[key] = {
            "id": trigger_id,
            "path": path,
            "method": method.upper(),
            "callback": callback,
            "name": name or path,
        }
        return trigger_id

    def unregister(self, trigger_id: str) -> None:
        to_remove = [k for k, v in self._routes.items() if v["id"] == trigger_id]
        for k in to_remove:
            del self._routes[k]

    @property
    def active_triggers(self) -> list[dict[str, str]]:
        return [
            {"id": v["id"], "path": v["path"], "method": v["method"], "name": v["name"]}
            for v in self._routes.values()
        ]

    async def start(self) -> None:
        self._server = await asyncio.start_server(
            self._handle_connection, self._host, self._port
        )

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    async def _handle_connection(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            request_line = await reader.readline()
            if not request_line:
                writer.close()
                return

            parts = request_line.decode("utf-8", errors="replace").strip().split()
            if len(parts) < 2:
                await self._send_response(writer, 400, "Bad Request")
                return

            method, path = parts[0], parts[1]

            headers: dict[str, str] = {}
            content_length = 0
            while True:
                line = await reader.readline()
                if line in (b"\r\n", b"\n", b""):
                    break
                decoded = line.decode("utf-8", errors="replace").strip()
                if ":" in decoded:
                    k, v = decoded.split(":", 1)
                    headers[k.strip().lower()] = v.strip()
                    if k.strip().lower() == "content-length":
                        content_length = int(v.strip())

            body = b""
            if content_length > 0:
                body = await reader.readexactly(content_length)

            key = f"{method}:{path}"
            route = self._routes.get(key)
            if route is None:
                await self._send_response(writer, 404, "Not Found")
                return

            callback = route["callback"]
            try:
                body_str = body.decode("utf-8", errors="replace") if body else ""
                if inspect.iscoroutinefunction(callback):
                    await callback(body_str)
                else:
                    callback(body_str)
                await self._send_response(writer, 200, "OK")
            except Exception as e:
                logger.error("Webhook callback error: %s", e)
                await self._send_response(writer, 500, "Internal Server Error")
        except Exception:
            logger.exception("Webhook connection error")
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    async def _send_response(
        self, writer: asyncio.StreamWriter, status: int, message: str
    ) -> None:
        body = json.dumps({"status": status, "message": message})
        response = (
            f"HTTP/1.1 {status} {message}\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(body)}\r\n"
            f"\r\n"
            f"{body}"
        )
        writer.write(response.encode())
        await writer.drain()
