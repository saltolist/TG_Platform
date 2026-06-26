"""Tests for tenant key resolution."""

from app.core.constants import DEMO_TENANT_PREFIX, GUEST_TOKEN_PREFIX, PRESENTATION_GUEST_TOKEN
from app.core.tenant import is_overlay_tenant, resolve_tenant_key


def test_resolve_guest_token_from_bearer():
    token = f"{GUEST_TOKEN_PREFIX}550e8400-e29b-41d4-a716-446655440000"
    assert resolve_tenant_key(f"Bearer {token}", None) == token


def test_resolve_demo_session_from_header():
    demo_key = f"{DEMO_TENANT_PREFIX}550e8400-e29b-41d4-a716-446655440000"
    assert resolve_tenant_key("Bearer jwt-token", demo_key) == demo_key


def test_legacy_presentation_guest_has_no_tenant():
    assert resolve_tenant_key(f"Bearer {PRESENTATION_GUEST_TOKEN}", None) is None


def test_is_overlay_tenant():
    assert is_overlay_tenant(f"{GUEST_TOKEN_PREFIX}abc") is True
    assert is_overlay_tenant(f"{DEMO_TENANT_PREFIX}abc") is True
    assert is_overlay_tenant(None) is False
    assert is_overlay_tenant("") is False
