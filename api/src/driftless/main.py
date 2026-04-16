"""FastAPI application entrypoint."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from driftless.api.routes_gauges import router as gauges_router
from driftless.api.routes_health import router as health_router
from driftless.api.routes_streams import router as streams_router
from driftless.api.routes_watch import router as watch_router
from driftless.config import get_settings
from driftless.scheduler import shutdown_scheduler, start_scheduler

logger = logging.getLogger("driftless")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logger.info("Starting Driftless API (ingest_enabled=%s)", settings.ingest_enabled)
    start_scheduler()
    try:
        yield
    finally:
        shutdown_scheduler()
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
app.include_router(streams_router)
app.include_router(gauges_router)
app.include_router(watch_router)
