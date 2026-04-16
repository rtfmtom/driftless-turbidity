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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
