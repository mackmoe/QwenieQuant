import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

import httpx
from fastapi import FastAPI

from app.config import get_settings
from app.postgres import init_pool
from app.routes import router, set_dependencies

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    pool = await init_pool(settings.postgres_url)
    http = httpx.AsyncClient(timeout=settings.http_timeout)
    set_dependencies(pool, http, settings)
    logger.info(
        "Risk Manager starting dry_run=%s min_confidence=%.2f min_edge=%.4f",
        settings.dry_run,
        settings.min_confidence,
        settings.min_edge,
    )
    try:
        yield
    finally:
        await http.aclose()
        if pool is not None:
            await pool.close()
        logger.info("Risk Manager stopped")


app = FastAPI(title="Risk Manager", version="0.1.0", lifespan=lifespan)
app.include_router(router)
