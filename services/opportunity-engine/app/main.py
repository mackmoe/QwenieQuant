import asyncio
import logging
from contextlib import asynccontextmanager, suppress
from typing import AsyncIterator

import httpx
from fastapi import FastAPI

from app.config import get_settings
from app.postgres import init_pool
from app.routes import router, set_dependencies
from app.scheduler import scheduler_loop

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
        "Opportunity Engine starting: interval=%ds tier2=%d tier3=%d",
        settings.discovery_interval_seconds,
        settings.max_tier2_markets,
        settings.max_tier3_markets,
    )

    task = asyncio.create_task(scheduler_loop(http, settings, pool))

    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        await http.aclose()
        if pool is not None:
            await pool.close()
        logger.info("Opportunity Engine stopped")


app = FastAPI(
    title="Opportunity Engine",
    description="Discovers and ranks Kalshi markets by analysis priority.",
    version="0.1.0",
    lifespan=lifespan,
)
app.include_router(router)
