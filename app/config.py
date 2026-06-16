"""Application configuration loaded from environment variables / .env.

All secrets and deployment-specific values are read here. Nothing is hard-coded.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Telegram
    telegram_bot_token: str = Field(default="", alias="TELEGRAM_BOT_TOKEN")

    # Database
    database_url: str = Field(
        default="sqlite+aiosqlite:///./data/887assistant.db", alias="DATABASE_URL"
    )

    # File storage
    file_storage_path: str = Field(default="./storage", alias="FILE_STORAGE_PATH")
    file_max_download_bytes: int = Field(default=20 * 1024 * 1024, alias="FILE_MAX_DOWNLOAD_BYTES")
    # Per-user storage quota in bytes; 0 = unlimited.
    file_storage_quota_bytes: int = Field(
        default=500 * 1024 * 1024, alias="FILE_STORAGE_QUOTA_BYTES"
    )

    # LLM / AI chat
    llm_provider: str = Field(default="moonshot", alias="LLM_PROVIDER")
    llm_api_key: str = Field(default="", alias="LLM_API_KEY")
    llm_model: str = Field(default="", alias="LLM_MODEL")
    llm_base_url: str = Field(default="", alias="LLM_BASE_URL")
    llm_max_history_messages: int = Field(default=50, alias="LLM_MAX_HISTORY_MESSAGES")
    llm_request_timeout: int = Field(default=60, alias="LLM_REQUEST_TIMEOUT")

    # AI web search
    web_search_enabled: bool = Field(default=True, alias="WEB_SEARCH_ENABLED")
    web_search_provider: str = Field(default="tavily", alias="WEB_SEARCH_PROVIDER")
    web_search_max_results: int = Field(default=5, alias="WEB_SEARCH_MAX_RESULTS")
    tavily_api_key: str = Field(default="", alias="TAVILY_API_KEY")

    # FACEIT
    faceit_api_key: str = Field(default="", alias="FACEIT_API_KEY")
    faceit_rate_limit_rps: float = Field(default=10.0, alias="FACEIT_RATE_LIMIT_RPS")
    faceit_cache_ttl: int = Field(default=86400, alias="FACEIT_CACHE_TTL")

    # Object storage (S3 / Cloudflare R2)
    storage_backend: str = Field(default="local", alias="STORAGE_BACKEND")  # "local" | "s3"
    s3_endpoint_url: str = Field(default="", alias="S3_ENDPOINT_URL")
    s3_access_key_id: str = Field(default="", alias="S3_ACCESS_KEY_ID")
    s3_secret_access_key: str = Field(default="", alias="S3_SECRET_ACCESS_KEY")
    s3_bucket: str = Field(default="", alias="S3_BUCKET")
    s3_region: str = Field(default="auto", alias="S3_REGION")  # Cloudflare R2 uses "auto"
    s3_public_base_url: str = Field(default="", alias="S3_PUBLIC_BASE_URL")

    # Calendar / web server
    base_url: str = Field(default="http://localhost:8080", alias="BASE_URL")
    web_host: str = Field(default="0.0.0.0", alias="WEB_HOST")
    web_port: int = Field(default=8080, alias="WEB_PORT")

    # Optional Google OAuth (two-way calendar sync)
    google_oauth_client_id: str = Field(default="", alias="GOOGLE_OAUTH_CLIENT_ID")
    google_oauth_client_secret: str = Field(default="", alias="GOOGLE_OAUTH_CLIENT_SECRET")
    google_oauth_redirect_uri: str = Field(default="", alias="GOOGLE_OAUTH_REDIRECT_URI")

    # Misc
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    default_timezone: str = Field(default="UTC", alias="DEFAULT_TIMEZONE")

    @property
    def sqlalchemy_url(self) -> str:
        """Normalise the DB URL for SQLAlchemy's async engine.

        Railway (and many managed Postgres providers) hand out URLs like
        ``postgres://...`` or ``postgresql://...``; SQLAlchemy's async engine
        needs the ``postgresql+asyncpg://`` driver. Rewrite the scheme prefix
        (everything up to ``://``) when necessary, leaving everything else as-is.
        """
        url = self.database_url
        if url.startswith("postgresql+asyncpg://"):
            return url
        for prefix in ("postgresql://", "postgres://"):
            if url.startswith(prefix):
                return "postgresql+asyncpg://" + url[len(prefix):]
        return url

    @property
    def is_sqlite(self) -> bool:
        return self.sqlalchemy_url.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    return Settings()
