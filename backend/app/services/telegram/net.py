"""Shared error type + Telethon network/credential helpers (Phase 3, Steps 1-2+).

Extracted from ``auth_flow.py`` so non-auth Telegram flows (e.g.
``channel_flow.py``) can reuse the same timeout/credential/error handling
instead of duplicating it.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, TypeVar

from app.core.config import Settings
from app.core.crypto import decrypt_byok, is_encrypted
from app.services.telegram.clock_sync import (
    apply_preferred_time_offset,
    measure_http_time_offset_seconds,
    reinforce_clock_after_telegram_rpc,
    refresh_telethon_clock,
)

logger = logging.getLogger(__name__)

_T = TypeVar("_T")

TELEGRAM_TIMEOUT_MESSAGE = (
    "Telegram не отвечает. Проверьте интернет/VPN или настройте TELEGRAM_PROXY_* "
    "(из Docker до серверов Telegram часто нет прямого доступа)."
)


class TelegramAuthError(Exception):
    """Raised for any Telegram-flow failure that should become an HTTP error.

    Despite the name (kept for backward compatibility with Step 1 imports),
    this is used by every Telethon-backed flow, not just authentication.

    ``profile_patch``, when set, is a full replacement for ``profile.telegram``
    that the caller (router) must still persist even though the request as a
    whole failed — e.g. an expired code resets ``authStatus`` back to ``idle``.
    """

    def __init__(
        self,
        detail: str,
        status_code: int = 400,
        profile_patch: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code
        self.profile_patch = profile_patch


async def with_timeout(coro: Any, settings: Settings) -> _T:
    """Bound any single Telethon network call so a stalled server can't hang a worker."""
    try:
        return await asyncio.wait_for(coro, timeout=settings.telegram_rpc_timeout_seconds)
    except asyncio.TimeoutError:
        raise TelegramAuthError(TELEGRAM_TIMEOUT_MESSAGE, 504) from None


async def connect_telegram_client(client: Any, settings: Settings) -> None:
    """Connect Telethon and align MTProto ``time_offset`` before updates are processed."""
    if settings.telegram_clock_sync_enabled:
        offset = await measure_http_time_offset_seconds()
        if offset is not None:
            apply_preferred_time_offset(client, offset)

    await with_timeout(client.connect(), settings)

    if not settings.telegram_clock_sync_enabled:
        return

    try:
        await with_timeout(client.get_me(), settings)
    except Exception:
        logger.debug("get_me after connect failed during clock sync", exc_info=True)

    await reinforce_clock_after_telegram_rpc(client, settings)


async def disconnect_safely(client: Any) -> None:
    """Best-effort disconnect — never let a stuck transport hide the real error."""
    try:
        await asyncio.wait_for(client.disconnect(), timeout=5.0)
    except Exception:  # noqa: BLE001 — cleanup only, original error already raised
        pass


def decrypt_field(value: str, settings: Settings) -> str:
    if not value:
        return ""
    return decrypt_byok(value, settings) if is_encrypted(value) else value


def require_api_credentials(profile: dict[str, Any], settings: Settings) -> tuple[int, str]:
    api_id_raw = str(profile.get("apiId") or "").strip()
    api_hash_raw = str(profile.get("apiHash") or "")
    if not api_id_raw or not api_hash_raw:
        raise TelegramAuthError("Сначала укажите API ID и API Hash", 400)
    try:
        api_id = int(api_id_raw)
    except ValueError:
        raise TelegramAuthError("API ID должен быть числом", 400) from None
    api_hash = decrypt_field(api_hash_raw, settings)
    if not api_hash:
        raise TelegramAuthError("Не удалось расшифровать API Hash", 400)
    return api_id, api_hash
