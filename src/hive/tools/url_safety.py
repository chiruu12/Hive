"""Shared URL validation and safe HTTP fetch helpers (SSRF protection).

HTTP requests pin the resolved IP in the request URL and send the original
hostname in the ``Host`` header, closing DNS-rebinding TOCTOU for cleartext
fetches.

HTTPS requests validate that the hostname resolves to a public address but
connect via the hostname (SNI/TLS). IP pinning is **not** applied for HTTPS
because pinning would require custom TLS/CONNECT handling and breaks many CDN
hostnames. Treat HTTPS as a smaller TOCTOU window, not zero risk; restrict
high-sensitivity deployments with an allowlist or a dedicated fetch proxy.
"""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

REQUEST_TIMEOUT = 10
MAX_REDIRECTS = 5
# Hard cap on bytes read off the wire before decoding -- prevents a huge or
# never-ending response from exhausting memory.
MAX_RESPONSE_BYTES = 5_000_000
DEFAULT_USER_AGENT = "HiveAgent/1.0"


def is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Return True if the IP must not be fetched (private, loopback, etc.)."""
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def validate_url(url: str) -> tuple[str | None, str | None]:
    """SSRF guard. Returns ``(error, validated_ip)``.

    Rejects non-http(s) schemes and any host that resolves to a non-public
    address (loopback, private, link-local incl. the cloud metadata IP
    169.254.169.254, reserved, multicast, or unspecified). On success the
    caller must connect to the returned ``validated_ip`` -- not re-resolve the
    hostname -- otherwise a DNS-rebinding host (TTL 0) could return a public IP
    here and an internal IP to the real connection (TOCTOU).
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return (
            f"Blocked: only http/https URLs are allowed (got '{parsed.scheme or 'none'}').",
            None,
        )
    host = parsed.hostname
    if not host:
        return "Blocked: URL has no host.", None
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        return f"Blocked: cannot resolve host '{host}': {e}", None
    validated_ip: str | None = None
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            continue
        if is_blocked_ip(ip):
            return f"Blocked: '{host}' resolves to a non-public address ({ip}).", None
        if validated_ip is None:
            validated_ip = str(ip)
    if validated_ip is None:
        return f"Blocked: could not resolve '{host}' to a usable address.", None
    return None, validated_ip


def build_pinned_request(
    url: str,
    validated_ip: str | None,
    *,
    user_agent: str = DEFAULT_USER_AGENT,
) -> tuple[str, dict[str, str]]:
    """Build request URL and headers with HTTP IP pinning when applicable."""
    parsed = urlparse(url)
    headers = {"User-Agent": user_agent}
    request_url = url
    if parsed.scheme == "http" and validated_ip:
        host_header = parsed.hostname or ""
        if parsed.port:
            host_header = f"{host_header}:{parsed.port}"
        headers["Host"] = host_header
        netloc_ip = validated_ip
        if parsed.port:
            netloc_ip = f"{validated_ip}:{parsed.port}"
        request_url = parsed._replace(netloc=netloc_ip).geturl()
    return request_url, headers


def _read_body_sync(response: httpx.Response, max_bytes: int) -> str:
    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_bytes():
        chunks.append(chunk)
        total += len(chunk)
        if total >= max_bytes:
            break
    return b"".join(chunks).decode(response.encoding or "utf-8", errors="replace")


async def _read_body_async(response: httpx.Response, max_bytes: int) -> str:
    chunks: list[bytes] = []
    total = 0
    async for chunk in response.aiter_bytes():
        chunks.append(chunk)
        total += len(chunk)
        if total >= max_bytes:
            break
    return b"".join(chunks).decode(response.encoding or "utf-8", errors="replace")


@dataclass(frozen=True)
class SafeFetchResult:
    """Outcome of a safe URL fetch."""

    ok: bool
    text: str = ""
    content_type: str = ""
    error: str | None = None


def fetch_url_safe_sync(
    url: str,
    *,
    timeout: float = REQUEST_TIMEOUT,
    max_redirects: int = MAX_REDIRECTS,
    max_response_bytes: int = MAX_RESPONSE_BYTES,
    user_agent: str = DEFAULT_USER_AGENT,
) -> SafeFetchResult:
    """Fetch a URL with SSRF guards, IP pinning, and per-hop redirect re-validation."""
    return request_url_safe_sync(
        url,
        method="GET",
        timeout=timeout,
        max_redirects=max_redirects,
        max_response_bytes=max_response_bytes,
        user_agent=user_agent,
    )


def request_url_safe_sync(
    url: str,
    *,
    method: str = "GET",
    params: dict[str, str] | None = None,
    data: dict[str, str] | None = None,
    timeout: float = REQUEST_TIMEOUT,
    max_redirects: int = MAX_REDIRECTS,
    max_response_bytes: int = MAX_RESPONSE_BYTES,
    user_agent: str = DEFAULT_USER_AGENT,
) -> SafeFetchResult:
    """HTTP request with SSRF guards, IP pinning, and per-hop redirect re-validation."""
    current = url
    try:
        for _ in range(max_redirects + 1):
            blocked, validated_ip = validate_url(current)
            if blocked:
                return SafeFetchResult(ok=False, error=blocked)
            request_url, headers = build_pinned_request(
                current, validated_ip, user_agent=user_agent
            )
            with httpx.stream(
                method,
                request_url,
                params=params if current == url else None,
                data=data if current == url else None,
                timeout=timeout,
                follow_redirects=False,
                headers=headers,
            ) as resp:
                if resp.is_redirect:
                    location = resp.headers.get("location")
                    if not location:
                        break
                    current = str(httpx.URL(current).join(location))
                    continue
                resp.raise_for_status()
                content_type = resp.headers.get("content-type", "")
                text = _read_body_sync(resp, max_response_bytes)
                return SafeFetchResult(ok=True, text=text, content_type=content_type)
        return SafeFetchResult(ok=False, error="Blocked: too many redirects.")
    except httpx.HTTPStatusError as e:
        return SafeFetchResult(
            ok=False,
            error=f"HTTP error {e.response.status_code}: {e.response.reason_phrase}",
        )
    except httpx.RequestError as e:
        return SafeFetchResult(ok=False, error=f"Request failed: {e}")


async def fetch_url_safe(
    url: str,
    *,
    timeout: float = REQUEST_TIMEOUT,
    max_redirects: int = MAX_REDIRECTS,
    max_response_bytes: int = MAX_RESPONSE_BYTES,
    user_agent: str = DEFAULT_USER_AGENT,
) -> SafeFetchResult:
    """Async fetch with SSRF guards, IP pinning, and per-hop redirect re-validation."""
    current = url
    try:
        for _ in range(max_redirects + 1):
            blocked, validated_ip = validate_url(current)
            if blocked:
                return SafeFetchResult(ok=False, error=blocked)
            request_url, headers = build_pinned_request(
                current, validated_ip, user_agent=user_agent
            )
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream(
                    "GET",
                    request_url,
                    follow_redirects=False,
                    headers=headers,
                ) as resp:
                    if resp.is_redirect:
                        location = resp.headers.get("location")
                        if not location:
                            break
                        current = str(httpx.URL(current).join(location))
                        continue
                    resp.raise_for_status()
                    content_type = resp.headers.get("content-type", "")
                    text = await _read_body_async(resp, max_response_bytes)
                    return SafeFetchResult(ok=True, text=text, content_type=content_type)
        return SafeFetchResult(ok=False, error="Blocked: too many redirects.")
    except httpx.HTTPStatusError as e:
        return SafeFetchResult(
            ok=False,
            error=f"HTTP error {e.response.status_code}: {e.response.reason_phrase}",
        )
    except httpx.RequestError as e:
        return SafeFetchResult(ok=False, error=f"Request failed: {e}")
