import asyncio
import logging

import httpx

from app.clients import LearningClient, PredictionClient, ReflectionClient
from app.config import get_settings
from app.discord_bot import create_bot

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)


async def main() -> None:
    settings = get_settings()

    http = httpx.AsyncClient(timeout=settings.http_timeout)
    try:
        prediction_client = PredictionClient(settings.prediction_api_url, http)
        learning_client = LearningClient(settings.learning_engine_url, http)
        reflection_client = ReflectionClient(settings.reflection_engine_url, http)

        bot = create_bot(
            prediction_client,
            learning_client,
            reflection_client,
            http,
            settings,
        )
        await bot.start(settings.discord_bot_token)
    finally:
        await http.aclose()


if __name__ == "__main__":
    asyncio.run(main())
