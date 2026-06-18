"""Tests for guest bearer token parsing."""

import uuid

import pytest

from app.core.guest_tokens import is_guest_token, parse_guest_id


def test_legacy_presentation_guest_token() -> None:
    assert is_guest_token("presentation:guest") is True
    assert parse_guest_id("presentation:guest") is None


def test_valid_guest_uuid_token() -> None:
    guest_id = str(uuid.uuid4())
    token = f"guest:{guest_id}"
    assert is_guest_token(token) is True
    assert parse_guest_id(token) == guest_id


def test_invalid_guest_token_rejected() -> None:
    assert is_guest_token("guest:not-a-uuid") is False
    assert is_guest_token("guest:") is False
    assert is_guest_token("presentation:evil") is False
    assert parse_guest_id("guest:not-a-uuid") is None


@pytest.mark.parametrize(
    "token",
    [
        "Bearer guest:123",
        "",
        "user-jwt-token",
    ],
)
def test_non_guest_tokens(token: str) -> None:
    assert is_guest_token(token) is False
