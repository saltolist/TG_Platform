"""Tests for Settings AI-related fields."""

from app.core.config import Settings


def test_rag_enabled_parses_string_flags() -> None:
    assert Settings(rag_enabled="1").rag_enabled is True
    assert Settings(rag_enabled="0").rag_enabled is False
    assert Settings(rag_enabled="true").rag_enabled is True
    assert Settings(rag_enabled="off").rag_enabled is False


def test_provider_keys_default_empty() -> None:
    settings = Settings()
    assert settings.openai_api_key == ""
    assert settings.deepseek_api_key == ""
