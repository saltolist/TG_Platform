from functools import lru_cache
from typing import Any

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    # AI provider keys (Phase 2) — empty by default; presentation/demo use stubs
    openai_api_key: str = ""
    deepseek_api_key: str = ""
    tavily_api_key: str = ""
    perplexity_api_key: str = ""
    serpapi_api_key: str = ""
    exa_api_key: str = ""
    rag_enabled: bool = False
    ai_context_log: bool = False
    # Chat id for LLM debug logs: gc1, post chat id, or post:postId:chatId
    ai_context_log_chat: str = ""

    @field_validator("rag_enabled", mode="before")
    @classmethod
    def _parse_rag_enabled(cls, value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return False

    @field_validator("ai_context_log", mode="before")
    @classmethod
    def _parse_ai_context_log(cls, value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return False

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
