import asyncio
import logging
from contextlib import asynccontextmanager, suppress
from typing import AsyncIterator

import httpx
from fastapi import FastAPI

from app.client import KalshiClient
from app.config import get_settings
from app import outcomes as outcomes_module
from app import postgres as postgres_module
from app.routes import router, set_client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    private_key_pem = settings.load_private_key_pem()
    http = httpx.AsyncClient(timeout=settings.http_timeout)
    client = KalshiClient(
        base_url=settings.base_url,
        api_key=settings.kalshi_api_key,
        private_key_pem=private_key_pem,
        http=http,
        max_retries=settings.max_retries,
    )
    set_client(client, settings.kalshi_environment)
    logger.info(
        "Kalshi connector starting environment=%s configured=%s outcome_collection=%s",
        settings.kalshi_environment,
        client.is_configured(),
        settings.outcome_collection_enabled,
    )

    pool = None
    if settings.postgres_url:
        try:
            pool = await postgres_module.init_pool(settings.postgres_url)
            logger.info("PostgreSQL pool ready for outcome collection")
        except Exception:
            logger.exception("PostgreSQL init failed; outcome collection disabled")

    outcome_task = asyncio.create_task(
        outcomes_module.outcome_loop(pool, client, http, settings)
    )

    try:
        yield
    finally:
        outcome_task.cancel()
        with suppress(asyncio.CancelledError):
            await outcome_task
        if pool is not None:
            await pool.close()
        await http.aclose()
        logger.info("Kalshi connector stopped")


app = FastAPI(title="Kalshi Connector", version="0.1.0", lifespan=lifespan)
app.include_router(router)
