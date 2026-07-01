"""Optional Telethon proxy (SOCKS5 / HTTP / MTProxy) for blocked MTProto networks."""

from __future__ import annotations

from typing import Any

from app.core.config import Settings

try:
    import socks
except ImportError:  # pragma: no cover
    socks = None  # type: ignore[assignment]


def build_telethon_proxy(settings: Settings) -> tuple[Any, ...] | None:
    """Return a Telethon ``proxy`` tuple or ``None`` when proxy is not configured."""
    proxy_type = (settings.telegram_proxy_type or "").strip().lower()
    host = (settings.telegram_proxy_host or "").strip()
    port = int(settings.telegram_proxy_port or 0)
    if not proxy_type or not host or port <= 0:
        return None
    if socks is None:
        raise RuntimeError("PySocks is required for TELEGRAM_PROXY_TYPE — pip install pysocks")

    username = (settings.telegram_proxy_username or "").strip() or None
    password = (settings.telegram_proxy_password or "").strip() or None

    if proxy_type == "socks5":
        return (socks.SOCKS5, host, port, True, username, password)
    if proxy_type in {"http", "https"}:
        return (socks.HTTP, host, port, True, username, password)
    if proxy_type == "mtproxy":
        secret = (settings.telegram_proxy_secret or "").strip()
        if not secret:
            raise ValueError("TELEGRAM_PROXY_SECRET is required for mtproxy")
        return ("mtproxy", host, port, secret)
    raise ValueError(f"Unsupported TELEGRAM_PROXY_TYPE: {proxy_type}")
