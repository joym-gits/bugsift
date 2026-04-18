from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    env: Literal["development", "production"] = Field(default="development", alias="BUGSIFT_ENV")
    public_url: str = Field(default="http://localhost:8080", alias="BUGSIFT_PUBLIC_URL")
    encryption_key: str = Field(default="", alias="BUGSIFT_ENCRYPTION_KEY")
    session_secret: str = Field(default="", alias="BUGSIFT_SESSION_SECRET")
    role: Literal["api", "worker"] = Field(default="api", alias="BUGSIFT_ROLE")

    database_url: str = Field(
        default="postgresql+asyncpg://bugsift:bugsift@localhost:5432/bugsift",
        alias="DATABASE_URL",
    )
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")

    github_app_id: str = Field(default="", alias="GITHUB_APP_ID")
    github_app_client_id: str = Field(default="", alias="GITHUB_APP_CLIENT_ID")
    github_app_client_secret: str = Field(default="", alias="GITHUB_APP_CLIENT_SECRET")
    github_app_webhook_secret: str = Field(default="", alias="GITHUB_APP_WEBHOOK_SECRET")
    github_app_private_key: str = Field(default="", alias="GITHUB_APP_PRIVATE_KEY")
    github_app_private_key_path: str = Field(default="", alias="GITHUB_APP_PRIVATE_KEY_PATH")

    @property
    def oauth_configured(self) -> bool:
        return bool(self.github_app_client_id and self.github_app_client_secret)

    @property
    def oauth_callback_url(self) -> str:
        return f"{self.public_url.rstrip('/')}/api/auth/github/callback"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
