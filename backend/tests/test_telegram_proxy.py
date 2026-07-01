"""Tests for optional Telethon proxy configuration."""

from __future__ import annotations

import pytest

from app.core.config import Settings
from app.services.telegram.proxy import build_telethon_proxy


def test_build_telethon_proxy_returns_none_when_unset() -> None:
    settings = Settings(telegram_proxy_type="", telegram_proxy_host="", telegram_proxy_port=0)
    assert build_telethon_proxy(settings) is None


def test_build_telethon_proxy_socks5() -> None:
    settings = Settings(
        telegram_proxy_type="socks5",
        telegram_proxy_host="127.0.0.1",
        telegram_proxy_port=1080,
        telegram_proxy_username="user",
        telegram_proxy_password="pass",
    )
    proxy = build_telethon_proxy(settings)
    assert proxy is not None
    assert proxy[1] == "127.0.0.1"
    assert proxy[2] == 1080


def test_build_telethon_proxy_mtproxy_requires_secret() -> None:
    settings = Settings(
        telegram_proxy_type="mtproxy",
        telegram_proxy_host="proxy.example",
        telegram_proxy_port=443,
        telegram_proxy_secret="",
    )
    with pytest.raises(ValueError, match="TELEGRAM_PROXY_SECRET"):
        build_telethon_proxy(settings)
