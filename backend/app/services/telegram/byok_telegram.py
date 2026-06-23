"""Encryption/masking utilities for sensitive fields in the Telegram profile.

The Telegram profile is stored as JSON in ``profiles.telegram``.

Sensitive fields that are encrypted at rest:
  - ``apiHash``      — MTProto API hash (never changes per app registration)
  - ``botApiToken``  — Telegram Bot API token (full bot control)
  - ``sessionString`` — Telethon session string (full account access; future field)

Non-sensitive fields (NOT encrypted):
  - ``apiId``       — numeric app ID, not a secret in itself
  - ``phone``       — phone number, stored for UX; not used to authenticate
  - ``channel``, ``channelTitle``, status/metric fields

Rules (mirror byok_profile.py):
- Already-encrypted values (prefix ``enc:v1:``) are kept as-is.
- Empty strings are not encrypted.
- When returning the profile to the client, real values are replaced with a
  preview (first 3 chars + 10 asterisks + last 3 chars).
- On save the client sends back a preview → original value is restored from
  ``previous_profile`` and then passed through encryption (opportunistic
  re-encrypt for legacy plaintext values).
"""

from __future__ import annotations

import copy
from typing import Any

from app.core.config import Settings, get_settings
from app.core.crypto import decrypt_byok, encrypt_byok, is_encrypted

# Fields encrypted at rest.
_SECRET_FIELDS = ("apiHash", "botApiToken", "sessionString")

PREVIEW_STAR_COUNT = 10


# ---------------------------------------------------------------------------
# Preview helpers
# ---------------------------------------------------------------------------


def mask_secret_preview(plaintext: str) -> str:
    """Return a client-safe preview: first 3 chars + 10 stars + last 3 chars."""
    if not plaintext:
        return ""
    stars = "*" * PREVIEW_STAR_COUNT
    if len(plaintext) >= 6:
        return plaintext[:3] + stars + plaintext[-3:]
    if len(plaintext) <= 3:
        return plaintext[:3].ljust(3, "*") + stars + plaintext[-3:].rjust(3, "*")
    return plaintext[:3] + stars + plaintext[-3:]


def is_secret_preview(value: str | None) -> bool:
    """True when *value* is a preview token (should not be saved as-is)."""
    if not value:
        return False
    marker = "*" * PREVIEW_STAR_COUNT
    pos = value.find(marker)
    return pos > 0 and pos <= 3


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _encrypt_field(value: str, settings: Settings | None) -> str:
    if not value or is_encrypted(value):
        return value
    return encrypt_byok(value, settings)


def _reveal_field(value: str, settings: Settings | None) -> str:
    if not value:
        return value
    if is_encrypted(value):
        return decrypt_byok(value, settings)
    return value


def _mask_field_for_response(value: str, settings: Settings | None) -> str:
    if not value:
        return value
    if is_encrypted(value):
        plaintext = decrypt_byok(value, settings)
        return mask_secret_preview(plaintext) if plaintext else ""
    return mask_secret_preview(value)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def encrypt_telegram_secrets(
    profile: dict[str, Any],
    settings: Settings | None = None,
    *,
    previous_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a copy of *profile* with sensitive fields encrypted.

    When the client sends back a preview token (meaning "don't change this
    field"), the original value is restored from *previous_profile* and then
    passed through encryption — so legacy plaintext values are opportunistically
    re-encrypted on next save.
    """
    settings = settings or get_settings()
    result = copy.deepcopy(profile)
    prev = previous_profile or {}

    for field in _SECRET_FIELDS:
        raw = str(result.get(field) or "")
        if is_secret_preview(raw):
            restored = str(prev.get(field) or "")
            result[field] = _encrypt_field(restored, settings)
        else:
            result[field] = _encrypt_field(raw, settings)

    return result


def mask_telegram_secrets(
    profile: dict[str, Any],
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Return a copy of *profile* with sensitive fields replaced by previews."""
    settings = settings or get_settings()
    result = copy.deepcopy(profile)

    for field in _SECRET_FIELDS:
        raw = str(result.get(field) or "")
        result[field] = _mask_field_for_response(raw, settings)

    return result


def reveal_telegram_secret(
    profile: dict[str, Any],
    *,
    field: str,
    settings: Settings | None = None,
) -> str | None:
    """Return the decrypted value of a single sensitive field, or None."""
    if field not in _SECRET_FIELDS:
        return None
    settings = settings or get_settings()
    raw = str(profile.get(field) or "")
    if not raw:
        return None
    return _reveal_field(raw, settings)
