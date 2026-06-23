"""Tests for Telegram secret encryption at rest.

Covers:
- byok_telegram.py: encrypt_telegram_secrets, mask_telegram_secrets, reveal_telegram_secret
- profile API: PUT encrypts, GET masks, POST /telegram/reveal-secret/ decrypts
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.core.config import Settings
from app.core.crypto import ENC_PREFIX, decrypt_byok, encrypt_byok
from app.services.telegram.byok_telegram import (
    PREVIEW_STAR_COUNT,
    encrypt_telegram_secrets,
    is_secret_preview,
    mask_secret_preview,
    mask_telegram_secrets,
    reveal_telegram_secret,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FERNET_TEST_KEY = "ZmDfcTF7_60GrrY167zsiPd67pEvs0aGOv2oasOM1Pg="


def _settings(*, enc_key: str = FERNET_TEST_KEY) -> Settings:
    return Settings(byok_encryption_key=enc_key)


def _profile(
    *,
    api_hash: str = "",
    bot_token: str = "",
    session_string: str = "",
    api_id: str = "12345678",
    phone: str = "+79001234567",
) -> dict:
    return {
        "apiId": api_id,
        "apiHash": api_hash,
        "phone": phone,
        "sessionName": "",
        "sessionString": session_string,
        "channel": "",
        "channelTitle": "",
        "authStatus": "idle",
        "authStep": "credentials",
        "channelStatus": "idle",
        "syncMode": "history-and-live",
        "lastSync": "—",
        "importedPosts": 0,
        "botApiToken": bot_token,
        "botStatus": "idle",
        "botUsername": "",
        "botLastActivity": "—",
        "botMessageCount": 0,
    }


# ---------------------------------------------------------------------------
# mask_secret_preview / is_secret_preview
# ---------------------------------------------------------------------------


class TestPreviewHelpers:
    def test_preview_format_long(self):
        result = mask_secret_preview("abc123abc123abc")
        stars = "*" * PREVIEW_STAR_COUNT
        assert result == f"abc{stars}abc"

    def test_preview_format_short(self):
        result = mask_secret_preview("ab")
        assert "*" * PREVIEW_STAR_COUNT in result

    def test_is_secret_preview_true(self):
        preview = mask_secret_preview("abc123abc123abc")
        assert is_secret_preview(preview)

    def test_is_secret_preview_false_for_plaintext(self):
        assert not is_secret_preview("abc123abc123abc")

    def test_is_secret_preview_false_for_empty(self):
        assert not is_secret_preview("")
        assert not is_secret_preview(None)


# ---------------------------------------------------------------------------
# encrypt_telegram_secrets
# ---------------------------------------------------------------------------


class TestEncryptTelegramSecrets:
    def test_api_hash_encrypted(self):
        p = _profile(api_hash="abc123abc123abc")
        result = encrypt_telegram_secrets(p, _settings())
        assert result["apiHash"].startswith(ENC_PREFIX)

    def test_bot_token_encrypted(self):
        p = _profile(bot_token="1234567890:ABC-token")
        result = encrypt_telegram_secrets(p, _settings())
        assert result["botApiToken"].startswith(ENC_PREFIX)

    def test_api_id_not_encrypted(self):
        p = _profile(api_id="12345678")
        result = encrypt_telegram_secrets(p, _settings())
        assert result["apiId"] == "12345678"

    def test_phone_not_encrypted(self):
        p = _profile(phone="+79001234567")
        result = encrypt_telegram_secrets(p, _settings())
        assert result["phone"] == "+79001234567"

    def test_empty_field_stays_empty(self):
        p = _profile(api_hash="")
        result = encrypt_telegram_secrets(p, _settings())
        assert result["apiHash"] == ""

    def test_already_encrypted_not_double_encrypted(self):
        s = _settings()
        enc = encrypt_byok("secret", s)
        p = _profile(api_hash=enc)
        result = encrypt_telegram_secrets(p, s)
        assert result["apiHash"] == enc

    def test_preview_restores_and_encrypts_from_previous(self):
        s = _settings()
        enc = encrypt_byok("secret-hash", s)
        prev = _profile(api_hash=enc)
        new_payload = _profile(api_hash=mask_secret_preview("secret-hash"))
        result = encrypt_telegram_secrets(new_payload, s, previous_profile=prev)
        stored = result["apiHash"]
        assert stored.startswith(ENC_PREFIX)
        assert decrypt_byok(stored, s) == "secret-hash"

    def test_preview_with_plaintext_previous_gets_encrypted(self):
        # Legacy plaintext in DB → client sends preview → opportunistic re-encrypt.
        s = _settings()
        prev = _profile(api_hash="secret-hash")  # plaintext in DB
        new_payload = _profile(api_hash=mask_secret_preview("secret-hash"))
        result = encrypt_telegram_secrets(new_payload, s, previous_profile=prev)
        stored = result["apiHash"]
        assert stored.startswith(ENC_PREFIX)
        assert decrypt_byok(stored, s) == "secret-hash"

    def test_preview_without_previous_becomes_empty(self):
        p = _profile(api_hash=mask_secret_preview("secret-hash"))
        result = encrypt_telegram_secrets(p, _settings())
        assert result["apiHash"] == ""

    def test_no_key_noop(self):
        s = _settings(enc_key="")
        p = _profile(api_hash="secret-hash")
        result = encrypt_telegram_secrets(p, s)
        assert result["apiHash"] == "secret-hash"

    def test_original_not_mutated(self):
        p = _profile(api_hash="secret-hash")
        encrypt_telegram_secrets(p, _settings())
        assert p["apiHash"] == "secret-hash"


# ---------------------------------------------------------------------------
# mask_telegram_secrets
# ---------------------------------------------------------------------------


class TestMaskTelegramSecrets:
    def test_plaintext_masked_as_preview(self):
        p = _profile(api_hash="abc123abc123abc")
        result = mask_telegram_secrets(p, _settings())
        assert is_secret_preview(result["apiHash"])

    def test_encrypted_masked_as_preview(self):
        s = _settings()
        enc = encrypt_byok("abc123abc123abc", s)
        p = _profile(api_hash=enc)
        result = mask_telegram_secrets(p, s)
        assert is_secret_preview(result["apiHash"])

    def test_empty_stays_empty(self):
        p = _profile(api_hash="")
        result = mask_telegram_secrets(p, _settings())
        assert result["apiHash"] == ""

    def test_api_id_not_masked(self):
        p = _profile(api_id="12345678")
        result = mask_telegram_secrets(p, _settings())
        assert result["apiId"] == "12345678"

    def test_original_not_mutated(self):
        p = _profile(api_hash="abc123abc123abc")
        mask_telegram_secrets(p, _settings())
        assert p["apiHash"] == "abc123abc123abc"


# ---------------------------------------------------------------------------
# reveal_telegram_secret
# ---------------------------------------------------------------------------


class TestRevealTelegramSecret:
    def test_reveals_encrypted_value(self):
        s = _settings()
        enc = encrypt_byok("secret-hash", s)
        p = _profile(api_hash=enc)
        revealed = reveal_telegram_secret(p, field="apiHash", settings=s)
        assert revealed == "secret-hash"

    def test_reveals_plaintext_value(self):
        p = _profile(api_hash="secret-hash")
        revealed = reveal_telegram_secret(p, field="apiHash", settings=_settings())
        assert revealed == "secret-hash"

    def test_empty_field_returns_none(self):
        p = _profile(api_hash="")
        assert reveal_telegram_secret(p, field="apiHash", settings=_settings()) is None

    def test_unknown_field_returns_none(self):
        p = _profile(api_hash="secret")
        assert reveal_telegram_secret(p, field="apiId", settings=_settings()) is None

    def test_session_string_revealed(self):
        s = _settings()
        enc = encrypt_byok("session-data-abc", s)
        p = _profile(session_string=enc)
        revealed = reveal_telegram_secret(p, field="sessionString", settings=s)
        assert revealed == "session-data-abc"


# ---------------------------------------------------------------------------
# Profile API contract tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_telegram_put_encrypts_get_masks(
    client: AsyncClient, writer_auth_headers: dict
) -> None:
    payload = {
        "authStatus": "idle",
        "authStep": "credentials",
        "apiId": "12345678",
        "apiHash": "abcdef1234567890abcdef1234567890",
        "phone": "+79001234567",
        "sessionName": "",
        "channel": "",
        "channelTitle": "",
        "channelStatus": "idle",
        "syncMode": "history-and-live",
        "lastSync": "—",
        "importedPosts": 0,
        "botApiToken": "",
        "botStatus": "idle",
        "botUsername": "",
        "botLastActivity": "—",
        "botMessageCount": 0,
    }
    put = await client.put(
        "/api/v1/profile/telegram/", headers=writer_auth_headers, json=payload
    )
    assert put.status_code == 200
    # PUT response must not expose raw api_hash.
    assert is_secret_preview(put.json()["apiHash"])
    assert put.json()["apiId"] == "12345678"

    get = await client.get("/api/v1/profile/telegram/", headers=writer_auth_headers)
    assert get.status_code == 200
    assert is_secret_preview(get.json()["apiHash"])


@pytest.mark.asyncio
async def test_telegram_reveal_secret(
    client: AsyncClient, writer_auth_headers: dict
) -> None:
    payload = {
        "authStatus": "idle",
        "authStep": "credentials",
        "apiId": "12345678",
        "apiHash": "abcdef1234567890abcdef1234567890",
        "phone": "+79001234567",
        "sessionName": "",
        "channel": "",
        "channelTitle": "",
        "channelStatus": "idle",
        "syncMode": "history-and-live",
        "lastSync": "—",
        "importedPosts": 0,
        "botApiToken": "",
        "botStatus": "idle",
        "botUsername": "",
        "botLastActivity": "—",
        "botMessageCount": 0,
    }
    await client.put("/api/v1/profile/telegram/", headers=writer_auth_headers, json=payload)

    reveal = await client.post(
        "/api/v1/profile/telegram/reveal-secret/",
        headers=writer_auth_headers,
        json={"field": "apiHash"},
    )
    assert reveal.status_code == 200
    assert reveal.json()["value"] == "abcdef1234567890abcdef1234567890"


@pytest.mark.asyncio
async def test_telegram_reveal_invalid_field(
    client: AsyncClient, writer_auth_headers: dict
) -> None:
    reveal = await client.post(
        "/api/v1/profile/telegram/reveal-secret/",
        headers=writer_auth_headers,
        json={"field": "apiId"},
    )
    assert reveal.status_code == 404
