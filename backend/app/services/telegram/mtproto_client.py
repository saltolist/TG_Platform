"""Thin factory around Telethon's ``TelegramClient``.

Every HTTP request gets its own short-lived client reconnected from a
``StringSession`` string (never a filesystem session file — see
docs/backend/phases/phase-3-telegram.md, Step 0). This module exists mainly
so tests can monkeypatch :data:`TelegramClient` without touching the
business logic in ``auth_flow.py``.
"""

from __future__ import annotations

from telethon import TelegramClient
from telethon.sessions import StringSession

from app.core.config import get_settings
from app.services.telegram.proxy import build_telethon_proxy

DEVICE_MODEL = "TG Platform"
APP_VERSION = "1.0"
SYSTEM_VERSION = "Linux"


def build_client(api_id: int, api_hash: str, session_string: str = "") -> TelegramClient:
    """Create a (not-yet-connected) Telethon client for *session_string*.

    An empty *session_string* starts a brand-new MTProto session (used for
    the very first ``send_code_request``); a non-empty one resumes a
    previously saved session (used to finish ``sign_in`` after the code/
    password is known).
    """
    settings = get_settings()
    proxy = build_telethon_proxy(settings)
    return TelegramClient(
        StringSession(session_string),
        api_id,
        api_hash,
        proxy=proxy,
        device_model=DEVICE_MODEL,
        app_version=APP_VERSION,
        system_version=SYSTEM_VERSION,
        connection_retries=5,
        retry_delay=2,
        timeout=30,
        request_retries=3,
    )


def save_session(client: TelegramClient) -> str:
    """Return the serialized ``StringSession`` for *client*."""
    return client.session.save()
