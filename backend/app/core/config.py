from functools import lru_cache
from typing import Any

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _parse_bool_env(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return False


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "TG Platform API"
    api_v1_prefix: str = "/api/v1"

    # Database
    database_url: str = "postgresql+asyncpg://tg:tg@localhost:5432/tg"

    # Auth / JWT
    jwt_secret: str = "change-me-please"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7  # 7 days

    # Auth cookie (httpOnly JWT transport for browser clients)
    jwt_cookie_name: str = "access_token"
    cookie_secure: bool = False
    # lax | strict | none — use none + secure for cross-origin frontend/backend
    cookie_samesite: str = "lax"
    # Empty = host-only cookie (recommended for localhost dev)
    cookie_domain: str = ""

    # CORS (comma-separated origins)
    cors_origins: str = "http://localhost:3000,http://localhost:3020,http://localhost:3021"

    # Email codes
    email_code_ttl_minutes: int = 15
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "no-reply@tg-platform.local"

    # Object storage (Phase 2)
    s3_endpoint: str = ""
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_bucket: str = "tg-media"

    # BYOK key encryption (Phase 2, step 5) — Fernet base64-encoded key.
    # Generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    # If empty, BYOK keys are stored as plaintext (dev/test fallback only).
    byok_encryption_key: str = ""

    # Comma-separated list of OLD Fernet keys used only for decryption during
    # key rotation.  New encryptions always use byok_encryption_key.
    # Example: BYOK_ENCRYPTION_OLD_KEYS=key2,key3
    # After running scripts/rotate_byok_key.py all enc:v1: values are
    # re-encrypted with the primary key and these can be cleared.
    byok_encryption_old_keys: str = ""

    # MTProto (Telethon) auth flow (Phase 3, step 1) — every Telethon network
    # call is wrapped in this timeout so a stuck/invalid api_id (Telegram can
    # silently stall instead of returning ApiIdInvalidError — see
    # https://github.com/LonamiWebs/Telethon/issues/1056) cannot hang a worker.
    telegram_rpc_timeout_seconds: float = 45.0
    telegram_listener_stop_timeout_seconds: float = 35.0
    # Pre-seed Telethon time_offset from HTTP Date headers (Docker macOS clock skew).
    telegram_clock_sync_enabled: bool = True
    # Optional proxy when MTProto is blocked (common in Docker / some ISPs).
    # socks5 | http | mtproxy — use host.docker.internal from Docker to reach a local VPN SOCKS port.
    telegram_proxy_type: str = ""
    telegram_proxy_host: str = ""
    telegram_proxy_port: int = 0
    telegram_proxy_secret: str = ""
    telegram_proxy_username: str = ""
    telegram_proxy_password: str = ""

    # Local media storage for Telegram import (Phase 3, step 3)
    media_storage_root: str = "media"
    media_public_base_url: str = "http://localhost:8000"
    telegram_import_post_limit: int = 200
    telegram_import_max_media_mb: float = 20.0
    telegram_import_timeout_seconds: float = 600.0

    # Live-sync (Phase 3 / Step 3.5) — long-lived Telethon event listeners
    telegram_live_sync_enabled: bool = True
    telegram_live_sync_registry_refresh_seconds: float = 30.0
    telegram_live_sync_reconnect_seconds: float = 15.0
    telegram_album_debounce_seconds: float = 2.0

    @property
    def byok_old_keys_list(self) -> list[str]:
        return [k.strip() for k in self.byok_encryption_old_keys.split(",") if k.strip()]

    # AI provider keys (Phase 2) — empty by default; presentation/demo use stubs
    openai_api_key: str = ""
    deepseek_api_key: str = ""
    perplexity_api_key: str = ""
    tavily_api_key: str = ""
    serpapi_api_key: str = ""
    exa_api_key: str = ""
    rag_enabled: bool = False
    ai_context_log: bool = False
    ai_context_stamps: bool = False
    # Chat id for LLM debug logs: gc1, post chat id, or post:postId:chatId
    ai_context_log_chat: str = ""

    # RAG parameters
    rag_top_k: int = 4
    # Minimum cosine similarity [0, 1] for a note to be included in retrieval results.
    # MiniLM models typically score 0.35–0.55 for relevant hits; e5 models score higher.
    rag_min_similarity: float = 0.38
    # Hard cap on note text fed to the embedder (chars); long notes are chunked
    rag_max_note_chars: int = 4000
    # Recent dialogue turns to prepend to the RAG embedding query (0 = current message only).
    rag_query_history_turns: int = 2
    # Max chars for the expanded RAG query sent to the embedder.
    rag_query_max_chars: int = 2000
    # When retrieval misses, rewrite the query via a short LLM call and retry once.
    rag_query_rewrite_on_miss: bool = True

    # Embeddings configuration
    # Local model name for fastembed (must be in TextEmbedding.list_supported_models())
    embedding_model_local: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    # Optional BYOK embeddings provider override (display name, e.g. "OpenAI")
    # When set, the user's embeddings key for this provider is used; otherwise local model.
    embedding_provider_byok: str = ""

    @field_validator(
        "rag_enabled",
        "ai_context_log",
        "ai_context_stamps",
        "rag_query_rewrite_on_miss",
        "cookie_secure",
        "telegram_live_sync_enabled",
        "telegram_clock_sync_enabled",
        mode="before",
    )
    @classmethod
    def _parse_bool_fields(cls, value: Any) -> bool:
        return _parse_bool_env(value)

    @field_validator("cookie_samesite", mode="before")
    @classmethod
    def _normalize_cookie_samesite(cls, value: Any) -> str:
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"lax", "strict", "none"}:
                return normalized
        return "lax"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
