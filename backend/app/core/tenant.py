"""Per-visitor tenant keys for presentation/demo overlay + RAG isolation."""

from __future__ import annotations

from app.core.constants import DEMO_TENANT_PREFIX, GUEST_TOKEN_PREFIX, PRESENTATION_GUEST_TOKEN
from app.core.guest_tokens import is_guest_token

TENANT_SESSION_HEADER = "X-Tenant-Session"


def resolve_tenant_key(
    authorization: str | None,
    x_tenant_session: str | None,
) -> str | None:
    """Resolve overlay tenant key from Bearer token and optional session header."""
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
        if is_guest_token(token) and token != PRESENTATION_GUEST_TOKEN:
            return token
        if token.startswith(GUEST_TOKEN_PREFIX):
            return token

    session_key = (x_tenant_session or "").strip()
    if session_key.startswith(DEMO_TENANT_PREFIX) and len(session_key) > len(DEMO_TENANT_PREFIX):
        return session_key
    if session_key.startswith(GUEST_TOKEN_PREFIX) and session_key != PRESENTATION_GUEST_TOKEN:
        return session_key

    return None


def is_overlay_tenant(tenant_key: str | None) -> bool:
    if not tenant_key:
        return False
    return tenant_key.startswith(GUEST_TOKEN_PREFIX) or tenant_key.startswith(DEMO_TENANT_PREFIX)
