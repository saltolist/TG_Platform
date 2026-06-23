"""Symmetric encryption for BYOK API keys stored in Postgres.

Keys are encrypted with Fernet (AES-128-CBC + HMAC-SHA256).
An encrypted value is prefixed with ``ENC_PREFIX`` so callers can detect
whether a stored value is ciphertext or a legacy plaintext / env-ref / demo stub.

If ``BYOK_ENCRYPTION_KEY`` is not configured the helpers act as identity
functions — useful for dev/test without Docker secrets.
"""

from __future__ import annotations

import logging

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)

ENC_PREFIX = "enc:v1:"


def _get_fernet(settings: Settings):
    """Return a Fernet instance or None when no key is configured."""
    key = (settings.byok_encryption_key or "").strip()
    if not key:
        return None
    try:
        from cryptography.fernet import Fernet

        return Fernet(key.encode())
    except Exception as exc:  # noqa: BLE001
        logger.error("Invalid BYOK_ENCRYPTION_KEY — encryption disabled: %s", exc)
        return None


def encrypt_byok(value: str, settings: Settings | None = None) -> str:
    """Encrypt a raw API key.

    Returns the original value unchanged when:
    - The value is empty.
    - The value starts with ``enc:v1:`` (already encrypted).
    - ``BYOK_ENCRYPTION_KEY`` is not set.
    """
    if not value or value.startswith(ENC_PREFIX):
        return value
    s = settings or get_settings()
    fernet = _get_fernet(s)
    if fernet is None:
        return value
    ciphertext = fernet.encrypt(value.encode()).decode()
    return ENC_PREFIX + ciphertext


def decrypt_byok(value: str, settings: Settings | None = None) -> str:
    """Decrypt a value previously encrypted by :func:`encrypt_byok`.

    Returns the original value unchanged when:
    - The value does not start with ``enc:v1:`` (plaintext / env-ref).
    - ``BYOK_ENCRYPTION_KEY`` is not set.
    """
    if not value or not value.startswith(ENC_PREFIX):
        return value
    s = settings or get_settings()
    fernet = _get_fernet(s)
    if fernet is None:
        logger.warning("Cannot decrypt BYOK key — BYOK_ENCRYPTION_KEY not set")
        return ""
    try:
        from cryptography.fernet import InvalidToken

        payload = value[len(ENC_PREFIX):]
        return fernet.decrypt(payload.encode()).decode()
    except InvalidToken:
        logger.error("Failed to decrypt BYOK key — wrong key or corrupted data")
        return ""


def is_encrypted(value: str) -> bool:
    return value.startswith(ENC_PREFIX)
