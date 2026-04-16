"""FastAPI application entrypoint."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from driftless.api.routes_health import router as health_router
from driftless.config import get_settings

logger = logging.getLogger("driftless")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logger.info("Starting Driftless API (ingest_enabled=%s)", settings.ingest_enabled)
    # Scheduler wiring is added in a later commit.
    try:
        yield
    finally:
        logger.info("Driftless API stopped")


app = FastAPI(title="Driftless Clarity API", version="0.1.0", lifespan=lifespan)

_settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=_settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
