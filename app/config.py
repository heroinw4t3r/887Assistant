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

    # LLM / AI chat
    llm_provider: str = Field(default="moonshot", alias="LLM_PROVIDER")
    llm_api_key: str = Field(default="", alias="LLM_API_KEY")
    llm_model: str = Field(default="", alias="LLM_MODEL")
    llm_base_url: str = Field(default="", alias="LLM_BASE_URL")
    llm_max_history_messages: int = Field(default=20, alias="LLM_MAX_HISTORY_MESSAGES")
    llm_request_timeout: int = Field(default=60, alias="LLM_REQUEST_TIMEOUT")

    # FACEIT
    faceit_api_key: str = Field(default="", alias="FACEIT_API_KEY")
    faceit_rate_limit_rps: float = Field(default=4.0, alias="FACEIT_RATE_LIMIT_RPS")
    faceit_cache_ttl: int = Field(default=600, alias="FACEIT_CACHE_TTL")

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
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    return Settings()
