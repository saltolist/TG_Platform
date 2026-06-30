"""Shared error type + Telethon network/credential helpers (Phase 3, Steps 1-2+).

Extracted from ``auth_flow.py`` so non-auth Telegram flows (e.g.
``channel_flow.py``) can reuse the same timeout/credential/error handling
instead of duplicating it.
"""

from __future__ import annotations

import asyncio
from typing import Any, TypeVar

from app.core.config import Settings
from app.core.crypto import decrypt_byok, is_encrypted

_T = TypeVar("_T")


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
        raise TelegramAuthError("Telegram не отвечает, попробуйте позже", 504) from None


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
