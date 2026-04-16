"""Application configuration loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        case_sensitive=False,
        env_prefix="",
    )

    database_url: str = "postgresql+psycopg://driftless:driftless@db:5432/driftless"
    ingest_enabled: bool = True
    ingest_interval_minutes: int = 15
    # Comma-separated in env (``CORS_ORIGINS=https://a,https://b``) or a list.
    # ``NoDecode`` keeps pydantic-settings from eagerly JSON-parsing the env
    # string so our ``_split_cors`` validator sees the raw value.
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:3000"]

    # MRMS (Chunk 2b). Clipping to a small bbox on ingest keeps transfer
    # and memory bounded. Defaults cover the Driftless region with a
    # generous margin; override via env if adding basins elsewhere.
    mrms_enabled: bool = True
    mrms_s3_bucket: str = "noaa-mrms-pds"
    mrms_product_prefix: str = "CONUS/MultiSensor_QPE_01H_Pass2_00.00"
    mrms_clip_west: float = -92.0
    mrms_clip_south: float = 42.5
    mrms_clip_east: float = -89.5
    mrms_clip_north: float = 44.0

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_cors(cls, v):
        if isinstance(v, str):
            return [s.strip() for s in v.split(",") if s.strip()]
        return v


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
