"""Server bind-time security checks."""

from __future__ import annotations

import ipaddress
import os

from hive.config import HiveConfig

_INSECURE_BIND_ENV = "HIVE_API_ALLOW_INSECURE"


def is_loopback_host(host: str) -> bool:
    """Return True when ``host`` binds only to local loopback interfaces."""
    normalized = host.strip().lower()
    if normalized in {"127.0.0.1", "localhost", "::1"}:
        return True
    try:
        addr = ipaddress.ip_address(normalized)
    except ValueError:
        return False
    return addr.is_loopback


def validate_serve_bind(host: str, config: HiveConfig) -> None:
    """Fail closed when serving on a non-loopback address without an API key.

    Loopback binds remain keyless (local-first default). Set
    ``HIVE_API_ALLOW_INSECURE=1`` to override for development only.
    """
    if is_loopback_host(host):
        return
    if os.environ.get(_INSECURE_BIND_ENV) == "1":
        return
    if config.server.api_key:
        return
    raise RuntimeError(
        f"Refusing to bind REST API to non-loopback host {host!r} without "
        f"server.api_key (or HIVE_API_KEY). Set {_INSECURE_BIND_ENV}=1 to "
        "override for local development only."
    )
