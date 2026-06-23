"""Tests for the 007 migration encryption pattern (reuses runtime helpers)."""

from __future__ import annotations

import json

from app.core.config import Settings
from app.core.crypto import ENC_PREFIX
from app.services.ai.byok_profile import encrypt_profile_keys
from app.services.telegram.byok_telegram import encrypt_telegram_secrets

FERNET_TEST_KEY = "ZmDfcTF7_60GrrY167zsiPd67pEvs0aGOv2oasOM1Pg="


def _settings() -> Settings:
    return Settings(byok_encryption_key=FERNET_TEST_KEY)


def test_migration_pattern_encrypts_vision_models():
    profile = {
        "llmModels": [],
        "webSearchModels": [],
        "orchestratorModels": [],
        "visionModels": [{"apiKey": "sk-vision-secret"}],
    }
    encrypted = encrypt_profile_keys(profile, _settings(), previous_profile=profile)
    assert encrypted["visionModels"][0]["apiKey"].startswith(ENC_PREFIX)


def test_migration_pattern_encrypts_embeddings_model():
    profile = {"embeddingsModel": {"provider": "OpenAI", "apiKey": "sk-embed"}}
    encrypted = encrypt_profile_keys(profile, _settings(), previous_profile=profile)
    assert encrypted["embeddingsModel"]["apiKey"].startswith(ENC_PREFIX)


def test_migration_pattern_is_idempotent_for_ai():
    profile = {
        "ragReasonerModels": [{"apiKey": "sk-rag-secret"}],
    }
    first = encrypt_profile_keys(profile, _settings(), previous_profile=profile)
    second = encrypt_profile_keys(first, _settings(), previous_profile=first)
    assert second == first


def test_migration_pattern_encrypts_telegram_secrets():
    profile = {"apiHash": "abcdef1234567890abcdef1234567890", "botApiToken": ""}
    encrypted = encrypt_telegram_secrets(profile, _settings(), previous_profile=profile)
    assert encrypted["apiHash"].startswith(ENC_PREFIX)


def test_migration_pattern_detects_ai_change():
    profile = {"webReasonerModels": [{"apiKey": "sk-web-reasoner"}]}
    encrypted = encrypt_profile_keys(profile, _settings(), previous_profile=profile)
    assert json.dumps(encrypted, sort_keys=True) != json.dumps(profile, sort_keys=True)
