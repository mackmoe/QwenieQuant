import asyncio
import logging
from datetime import datetime, timezone

import httpx

from app.clients import LearningClient, OpportunityClient, PredictionClient, PredictionQueueClient, ReflectionClient, RiskManagerClient
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
        opportunity_client = OpportunityClient(settings.opportunity_engine_url, http)
        queue_client = PredictionQueueClient(settings.prediction_queue_url, http)
        risk_manager_client = RiskManagerClient(settings.risk_manager_url, http)
        bot_start_time = datetime.now(timezone.utc)

        bot = create_bot(
            prediction_client,
            learning_client,
            reflection_client,
            opportunity_client,
            queue_client,
            risk_manager_client,
            http,
            settings,
            bot_start_time,
        )
        await bot.start(settings.discord_bot_token)
    finally:
        await http.aclose()


if __name__ == "__main__":
    asyncio.run(main())
