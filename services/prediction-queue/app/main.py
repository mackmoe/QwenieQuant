import asyncio
import logging
from contextlib import asynccontextmanager, suppress
from typing import AsyncIterator

import httpx
from fastapi import FastAPI

from app.config import get_settings
from app import postgres as postgres_module
from app import scheduler as scheduler_module
from app.routes import router, set_dependencies

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    pool = await postgres_module.init_pool(settings.postgres_url)
    set_dependencies(pool, settings)

    logger.info(
        "Prediction Queue Manager starting: max_size=%d refresh=%ds workflow=%s dry_run=%s",
        settings.queue_max_size,
        settings.queue_refresh_seconds,
        settings.workflow_enabled,
        settings.dry_run,
    )

    http_client = httpx.AsyncClient()
    refresh_task = asyncio.create_task(scheduler_module.scheduler_loop(pool, settings))
    workflow_task = asyncio.create_task(
        scheduler_module.workflow_loop(pool, http_client, settings)
    )

    try:
        yield
    finally:
        for task in (workflow_task, refresh_task):
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        await http_client.aclose()
        if pool is not None:
            await pool.close()
        logger.info("Prediction Queue Manager stopped")


app = FastAPI(
    title="Prediction Queue Manager",
    description="Traffic controller: maintains an ordered queue of markets awaiting prediction.",
    version="0.1.0",
    lifespan=lifespan,
)
app.include_router(router)
