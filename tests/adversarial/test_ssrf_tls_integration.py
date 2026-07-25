"""Integration tests: HTTPS IP pinning with real TLS (not mocked httpx).

Mock-based tests in ``tests/tools/test_url_safety.py`` assert that pinned URL,
Host, and ``sni_hostname`` are passed into ``httpx.stream()``. These tests prove
httpx actually completes a TLS handshake to the pinned IP while validating the
certificate for the original hostname via SNI.
"""

from __future__ import annotations

import http.server
import ssl
import subprocess
import threading
from collections.abc import Iterator
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import httpx
import pytest

from hive.tools.url_safety import fetch_url_safe, request_url_safe_sync

_PIN_HOSTNAME = "pin-test.example"
_PIN_BODY = b"pinned-tls-ok"


class _PinnedTlsHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(_PIN_BODY)

    def log_message(self, format: str, *args: object) -> None:
        return


def _generate_self_signed_cert(hostname: str, directory: Path) -> tuple[Path, Path]:
    key_path = directory / "key.pem"
    cert_path = directory / "cert.pem"
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-keyout",
            str(key_path),
            "-out",
            str(cert_path),
            "-days",
            "1",
            "-nodes",
            "-subj",
            f"/CN={hostname}",
        ],
        check=True,
        capture_output=True,
    )
    return cert_path, key_path


class _TlsPinnedServer:
    """Minimal HTTPS server on 127.0.0.1 for pinned-IP integration tests."""

    def __init__(self, hostname: str) -> None:
        self.hostname = hostname
        self._tmpdir = TemporaryDirectory()
        cert_path, key_path = _generate_self_signed_cert(hostname, Path(self._tmpdir.name))
        self._httpd = http.server.HTTPServer(("127.0.0.1", 0), _PinnedTlsHandler)
        self.port = self._httpd.server_address[1]
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(certfile=str(cert_path), keyfile=str(key_path))
        self._httpd.socket = ctx.wrap_socket(self._httpd.socket, server_side=True)
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    @property
    def url(self) -> str:
        return f"https://{self.hostname}:{self.port}/"

    def close(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
        self._tmpdir.cleanup()


@pytest.fixture
def tls_pinned_server() -> Iterator[_TlsPinnedServer]:
    server = _TlsPinnedServer(_PIN_HOSTNAME)
    try:
        yield server
    finally:
        server.close()


class _InsecureSyncClient(httpx.Client):
    """Real httpx client with cert verification disabled for self-signed test certs."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        kwargs["verify"] = False  # type: ignore[typeddict-unknown-key]
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]


class _InsecureAsyncClient(httpx.AsyncClient):
    """Real async httpx client with cert verification disabled for self-signed test certs."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        kwargs["verify"] = False  # type: ignore[typeddict-unknown-key]
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]


def test_https_ip_pinning_completes_real_tls_sync(
    tls_pinned_server: _TlsPinnedServer,
) -> None:
    """Sync fetch must reach a loopback TLS server via pinned IP + SNI."""
    with (
        patch(
            "hive.tools.url_safety.validate_url",
            side_effect=lambda url: (None, "127.0.0.1"),
        ),
        patch("hive.tools.url_safety.httpx.Client", _InsecureSyncClient),
    ):
        result = request_url_safe_sync(tls_pinned_server.url, timeout=5.0)

    assert result.ok, result.error
    assert result.text == _PIN_BODY.decode()


@pytest.mark.asyncio
async def test_https_ip_pinning_completes_real_tls_async(
    tls_pinned_server: _TlsPinnedServer,
) -> None:
    """Async fetch must reach a loopback TLS server via pinned IP + SNI."""
    with (
        patch(
            "hive.tools.url_safety.validate_url",
            side_effect=lambda url: (None, "127.0.0.1"),
        ),
        patch("hive.tools.url_safety.httpx.AsyncClient", _InsecureAsyncClient),
    ):
        result = await fetch_url_safe(tls_pinned_server.url, timeout=5.0)

    assert result.ok, result.error
    assert result.text == _PIN_BODY.decode()


def test_https_without_ip_pinning_cannot_reach_loopback_server(
    tls_pinned_server: _TlsPinnedServer,
) -> None:
    """Negative control: hostname-only URL must not reach our loopback TLS server."""
    with httpx.Client(verify=False, timeout=2.0) as client:
        with pytest.raises(httpx.RequestError):
            with client.stream("GET", tls_pinned_server.url, follow_redirects=False):
                pass
