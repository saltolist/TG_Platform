"""Tests for BYOK key encryption at rest (Phase 2, step 5).

Covers:
- crypto.py round-trip (encrypt/decrypt)
- byok_profile.py: encrypt_profile_keys, mask_profile_keys, decrypt_model_api_key
- keys.py: resolve_api_key transparently decrypts enc:v1: values
- profile API: PUT encrypts, GET masks
"""

from __future__ import annotations

import uuid

import pytest

from app.core.config import Settings
from app.core.constants import DEMO_EMAIL, PRESENTATION_EMAIL
from app.core.crypto import ENC_PREFIX, decrypt_byok, encrypt_byok, is_encrypted
from app.db.models import User
from app.services.ai.byok_profile import (
    MASKED_VALUE,
    decrypt_model_api_key,
    encrypt_profile_keys,
    is_api_key_preview,
    mask_api_key_preview,
    mask_profile_keys,
    reveal_model_api_key_from_profile,
    reveal_profile_keys_for_owner,
)
from app.services.ai.keys import (
    AccountMode,
    KeySource,
    LlmModelKey,
    resolve_api_key,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FERNET_TEST_KEY = "ZmDfcTF7_60GrrY167zsiPd67pEvs0aGOv2oasOM1Pg="


def _settings(*, enc_key: str = FERNET_TEST_KEY, openai: str = "", deepseek: str = "") -> Settings:
    return Settings(
        byok_encryption_key=enc_key,
        openai_api_key=openai,
        deepseek_api_key=deepseek,
    )


def _user(*, email: str = "author@example.com", is_seed: bool = False) -> User:
    return User(id=uuid.uuid4(), email=email, password_hash="hash", is_seed=is_seed)


def _real_user() -> User:
    return _user()


def _demo_user() -> User:
    return _user(email=DEMO_EMAIL, is_seed=True)


def _presentation_user() -> User:
    return _user(email=PRESENTATION_EMAIL, is_seed=True)


# ---------------------------------------------------------------------------
# crypto.py — round-trip
# ---------------------------------------------------------------------------


class TestCrypto:
    def test_encrypt_decrypt_round_trip(self):
        s = _settings()
        ciphertext = encrypt_byok("sk-real-key", s)
        assert ciphertext.startswith(ENC_PREFIX)
        assert decrypt_byok(ciphertext, s) == "sk-real-key"

    def test_encrypt_empty_returns_empty(self):
        assert encrypt_byok("", _settings()) == ""

    def test_encrypt_already_encrypted_is_idempotent(self):
        s = _settings()
        first = encrypt_byok("sk-abc", s)
        second = encrypt_byok(first, s)
        assert second == first

    def test_decrypt_plaintext_passthrough(self):
        assert decrypt_byok("sk-plain", _settings()) == "sk-plain"

    def test_decrypt_env_ref_passthrough(self):
        assert decrypt_byok("env:OPENAI_API_KEY", _settings()) == "env:OPENAI_API_KEY"

    def test_is_encrypted(self):
        s = _settings()
        enc = encrypt_byok("sk-x", s)
        assert is_encrypted(enc)
        assert not is_encrypted("sk-plain")
        assert not is_encrypted("")

    def test_no_key_encrypt_is_noop(self):
        s = _settings(enc_key="")
        assert encrypt_byok("sk-real", s) == "sk-real"

    def test_no_key_decrypt_returns_empty_for_enc_value(self):
        s_with_key = _settings()
        enc = encrypt_byok("sk-real", s_with_key)
        s_no_key = _settings(enc_key="")
        assert decrypt_byok(enc, s_no_key) == ""


# ---------------------------------------------------------------------------
# byok_profile.py — encrypt_profile_keys
# ---------------------------------------------------------------------------


class TestMaskApiKeyPreview:
    def test_preview_format(self):
        assert mask_api_key_preview("sk-real-secret-key") == "sk-**********key"

    def test_is_api_key_preview(self):
        assert is_api_key_preview("sk-**********key")
        assert is_api_key_preview(MASKED_VALUE)
        assert not is_api_key_preview("sk-real")


class TestEncryptProfileKeys:
    def _make_profile(self, api_key: str) -> dict:
        return {
            "llmModels": [{"provider": "OpenAI", "model": "gpt-4o", "apiKey": api_key}],
            "webSearchModels": [],
            "orchestratorModels": [],
        }

    def test_real_key_is_encrypted(self):
        profile = self._make_profile("sk-real-key")
        result = encrypt_profile_keys(profile, _settings())
        stored_key = result["llmModels"][0]["apiKey"]
        assert stored_key.startswith(ENC_PREFIX)

    def test_env_ref_not_encrypted(self):
        profile = self._make_profile("env:OPENAI_API_KEY")
        result = encrypt_profile_keys(profile, _settings())
        assert result["llmModels"][0]["apiKey"] == "env:OPENAI_API_KEY"

    def test_demo_fixture_key_not_encrypted(self):
        profile = self._make_profile("sk-openai-demo")
        result = encrypt_profile_keys(profile, _settings())
        assert result["llmModels"][0]["apiKey"] == "sk-openai-demo"

    def test_empty_key_not_encrypted(self):
        profile = self._make_profile("")
        result = encrypt_profile_keys(profile, _settings())
        assert result["llmModels"][0]["apiKey"] == ""

    def test_already_encrypted_not_double_encrypted(self):
        s = _settings()
        enc = encrypt_byok("sk-real", s)
        profile = self._make_profile(enc)
        result = encrypt_profile_keys(profile, s)
        assert result["llmModels"][0]["apiKey"] == enc

    def test_preview_value_restores_from_previous(self):
        s = _settings()
        enc = encrypt_byok("sk-real", s)
        prev = self._make_profile(enc)
        new_payload = self._make_profile(mask_api_key_preview("sk-real"))
        result = encrypt_profile_keys(new_payload, s, previous_profile=prev)
        assert result["llmModels"][0]["apiKey"] == enc

    def test_masked_value_restores_from_previous(self):
        s = _settings()
        enc = encrypt_byok("sk-real", s)
        prev = self._make_profile(enc)
        new_payload = self._make_profile(MASKED_VALUE)
        result = encrypt_profile_keys(new_payload, s, previous_profile=prev)
        assert result["llmModels"][0]["apiKey"] == enc

    def test_masked_value_without_previous_becomes_empty(self):
        profile = self._make_profile(MASKED_VALUE)
        result = encrypt_profile_keys(profile, _settings())
        assert result["llmModels"][0]["apiKey"] == ""

    def test_embeddings_model_encrypted(self):
        s = _settings()
        profile = {"embeddingsModel": {"provider": "OpenAI", "apiKey": "sk-embed"}}
        result = encrypt_profile_keys(profile, s)
        assert result["embeddingsModel"]["apiKey"].startswith(ENC_PREFIX)


# ---------------------------------------------------------------------------
# byok_profile.py — reveal_profile_keys_for_owner
# ---------------------------------------------------------------------------


class TestRevealModelApiKeyFromProfile:
    def test_reveals_encrypted_key_by_model_id(self):
        s = _settings()
        enc = encrypt_byok("sk-owner-secret-key", s)
        profile = {
            "llmModels": [{"id": "llm-1", "apiKey": enc}],
        }
        revealed = reveal_model_api_key_from_profile(
            profile,
            model_id="llm-1",
            field="llmModels",
            settings=s,
        )
        assert revealed == "sk-owner-secret-key"

    def test_missing_model_returns_none(self):
        assert (
            reveal_model_api_key_from_profile(
                {"llmModels": []},
                model_id="missing",
                field="llmModels",
                settings=_settings(),
            )
            is None
        )


# ---------------------------------------------------------------------------
# byok_profile.py — reveal_profile_keys_for_owner (legacy helper)
# ---------------------------------------------------------------------------


class TestRevealProfileKeysForOwner:
    def test_encrypted_key_revealed_as_plaintext(self):
        s = _settings()
        enc = encrypt_byok("sk-real-secret", s)
        profile = {"llmModels": [{"apiKey": enc}]}
        result = reveal_profile_keys_for_owner(profile, s)
        assert result["llmModels"][0]["apiKey"] == "sk-real-secret"

    def test_env_ref_unchanged(self):
        profile = {"llmModels": [{"apiKey": "env:OPENAI_API_KEY"}]}
        result = reveal_profile_keys_for_owner(profile, _settings())
        assert result["llmModels"][0]["apiKey"] == "env:OPENAI_API_KEY"


# ---------------------------------------------------------------------------
# byok_profile.py — mask_profile_keys
# ---------------------------------------------------------------------------


class TestMaskProfileKeys:
    def test_real_key_masked_as_preview(self):
        s = _settings()
        profile = {"llmModels": [{"apiKey": "sk-real-key"}]}
        result = mask_profile_keys(profile, s)
        assert result["llmModels"][0]["apiKey"] == "sk-**********key"

    def test_encrypted_key_masked_as_preview(self):
        s = _settings()
        enc = encrypt_byok("sk-real", s)
        profile = {"llmModels": [{"apiKey": enc}]}
        result = mask_profile_keys(profile, s)
        assert result["llmModels"][0]["apiKey"] == "sk-**********eal"

    def test_env_ref_not_masked(self):
        profile = {"llmModels": [{"apiKey": "env:OPENAI_API_KEY"}]}
        result = mask_profile_keys(profile)
        assert result["llmModels"][0]["apiKey"] == "env:OPENAI_API_KEY"

    def test_demo_fixture_key_not_masked(self):
        profile = {"llmModels": [{"apiKey": "sk-openai-demo"}]}
        result = mask_profile_keys(profile)
        assert result["llmModels"][0]["apiKey"] == "sk-openai-demo"

    def test_empty_key_not_masked(self):
        profile = {"llmModels": [{"apiKey": ""}]}
        result = mask_profile_keys(profile)
        assert result["llmModels"][0]["apiKey"] == ""

    def test_original_profile_not_mutated(self):
        profile = {"llmModels": [{"apiKey": "sk-real"}]}
        mask_profile_keys(profile)
        assert profile["llmModels"][0]["apiKey"] == "sk-real"


# ---------------------------------------------------------------------------
# byok_profile.py — decrypt_model_api_key
# ---------------------------------------------------------------------------


class TestDecryptModelApiKey:
    def test_decrypts_enc_value(self):
        s = _settings()
        enc = encrypt_byok("sk-real", s)
        assert decrypt_model_api_key(enc, s) == "sk-real"

    def test_plaintext_passthrough(self):
        assert decrypt_model_api_key("sk-plain", _settings()) == "sk-plain"

    def test_env_ref_passthrough(self):
        val = "env:OPENAI_API_KEY"
        assert decrypt_model_api_key(val, _settings()) == val

    def test_empty_passthrough(self):
        assert decrypt_model_api_key("", _settings()) == ""


# ---------------------------------------------------------------------------
# keys.py — resolve_api_key decrypts enc:v1: transparently
# ---------------------------------------------------------------------------


class TestResolveApiKeyWithEncryption:
    def test_encrypted_byok_resolves_to_plaintext_for_real_user(self):
        s = _settings()
        enc = encrypt_byok("sk-real-key", s)
        model = LlmModelKey(provider="OpenAI", api_key=enc)
        result = resolve_api_key(model, _real_user(), s)
        assert result.source == KeySource.BYOK
        assert result.api_key == "sk-real-key"
        assert result.account_mode == AccountMode.REAL

    def test_encrypted_byok_resolves_for_demo_user(self):
        s = _settings()
        enc = encrypt_byok("sk-real-key", s)
        model = LlmModelKey(provider="OpenAI", api_key=enc)
        result = resolve_api_key(model, _demo_user(), s)
        assert result.source == KeySource.BYOK
        assert result.api_key == "sk-real-key"

    def test_env_ref_still_works_after_encryption_feature(self):
        s = _settings(openai="sk-from-env")
        model = LlmModelKey(provider="OpenAI", api_key="env:OPENAI_API_KEY")
        result = resolve_api_key(model, _demo_user(), s)
        assert result.source == KeySource.ENV_REF
        assert result.api_key == "sk-from-env"

    def test_env_fallback_still_works(self):
        s = _settings(deepseek="sk-deepseek-env")
        model = LlmModelKey(provider="DeepSeek", api_key="")
        result = resolve_api_key(model, _presentation_user(), s)
        assert result.source == KeySource.ENV_FALLBACK
        assert result.api_key == "sk-deepseek-env"

    def test_no_key_real_user_unavailable(self):
        s = _settings()
        model = LlmModelKey(provider="OpenAI", api_key="")
        result = resolve_api_key(model, _real_user(), s)
        assert result.unavailable

    def test_decrypt_failure_returns_unavailable_for_real_user(self):
        # Key encrypted with one Fernet key, resolved with a different one.
        s_enc = _settings(enc_key="ZmDfcTF7_60GrrY167zsiPd67pEvs0aGOv2oasOM1Pg=")
        enc = encrypt_byok("sk-secret", s_enc)
        # Use a different valid Fernet key that can't decrypt the above.
        wrong_key = "NuHMRFG5TrNRfQEuL1dCJqHnU4hWpxMzKqD1uKfKVL8="
        s_wrong = _settings(enc_key=wrong_key)
        model = LlmModelKey(provider="OpenAI", api_key=enc)
        result = resolve_api_key(model, _real_user(), s_wrong)
        # Decryption returns "" → treated as no key → unavailable for real user.
        assert result.unavailable
