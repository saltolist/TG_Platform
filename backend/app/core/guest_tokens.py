"""Guest bearer tokens for presentation mode (ChatGPT-style anonymous sessions)."""

from __future__ import annotations

import uuid

from app.core.constants import GUEST_TOKEN_PREFIX, PRESENTATION_GUEST_TOKEN


def is_guest_token(token: str) -> bool:
    if token == PRESENTATION_GUEST_TOKEN:
        return True
    if not token.startswith(GUEST_TOKEN_PREFIX):
        return False
    guest_id = token[len(GUEST_TOKEN_PREFIX) :]
    return _is_valid_guest_id(guest_id)


def parse_guest_id(token: str) -> str | None:
    if token == PRESENTATION_GUEST_TOKEN:
        return None
    if not token.startswith(GUEST_TOKEN_PREFIX):
        return None
    guest_id = token[len(GUEST_TOKEN_PREFIX) :]
    if not _is_valid_guest_id(guest_id):
        return None
    return guest_id


def _is_valid_guest_id(value: str) -> bool:
    try:
        parsed = uuid.UUID(value)
    except ValueError:
        return False
    return str(parsed) == value.lower()
