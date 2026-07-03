import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

import httpx
from fastapi import FastAPI

from app.client import KalshiClient
from app.config import get_settings
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
        "Kalshi connector starting environment=%s configured=%s",
        settings.kalshi_environment,
        client.is_configured(),
    )
    try:
        yield
    finally:
        await http.aclose()
        logger.info("Kalshi connector stopped")


app = FastAPI(title="Kalshi Connector", version="0.1.0", lifespan=lifespan)
app.include_router(router)
