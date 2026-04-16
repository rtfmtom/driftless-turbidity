"""Application configuration loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    database_url: str = "postgresql+psycopg://driftless:driftless@db:5432/driftless"
    ingest_enabled: bool = True
    ingest_interval_minutes: int = 15
    cors_origins: list[str] = ["http://localhost:3000"]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
