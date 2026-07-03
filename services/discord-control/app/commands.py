"""
Command handler functions — pure async logic with no Discord coupling.

Each handler receives clients and settings as arguments and returns a
formatted string ready to send as a Discord message. discord_bot.py
wires these to slash commands and enforces authorization.

Keeping business logic here (instead of in discord_bot.py) makes every
handler unit-testable without Discord objects.
"""

import logging
import time

from app.clients import PredictionClient, LearningClient, ReflectionClient
from app.config import Settings
from app.formatter import (
    UNAUTHORIZED_MESSAGE,
    format_analysis,
    format_error,
    format_prediction,
    format_reflection,
    format_status,
)
from app.health import check_all_services

logger = logging.getLogger(__name__)


def is_authorized(user_id: int, allowed_user_ids: list[int]) -> bool:
    """Return True when user_id is in the operator-configured allow-list."""
    return user_id in allowed_user_ids


async def handle_status(
    prediction_client: PredictionClient,
    learning_client: LearningClient,
    reflection_client: ReflectionClient,
    http,
    settings: Settings,
) -> str:
    start = time.monotonic()
    health = await check_all_services(
        prediction_client, learning_client, reflection_client, http, settings
    )
    elapsed_ms = int((time.monotonic() - start) * 1000)
    logger.info("status elapsed=%dms", elapsed_ms)
    return format_status(health)


async def handle_predict(
    question: str,
    category: str,
    user_id: int,
    prediction_client: PredictionClient,
) -> str:
    start = time.monotonic()
    result = await prediction_client.predict(question, category)
    elapsed_ms = int((time.monotonic() - start) * 1000)
    logger.info(
        "predict user=%d category=%s elapsed=%dms success=%s",
        user_id,
        category,
        elapsed_ms,
        "error" not in result,
    )
    return format_prediction(result)


async def handle_analyze(
    user_id: int,
    learning_client: LearningClient,
) -> str:
    start = time.monotonic()
    result = await learning_client.analyze()
    elapsed_ms = int((time.monotonic() - start) * 1000)
    logger.info(
        "analyze user=%d elapsed=%dms success=%s",
        user_id,
        elapsed_ms,
        "error" not in result,
    )
    return format_analysis(result)


async def handle_reflect(
    user_id: int,
    learning_client: LearningClient,
    reflection_client: ReflectionClient,
) -> str:
    start = time.monotonic()

    # Run a fresh analysis to obtain an analysis_id, then reflect on it.
    analysis = await learning_client.analyze()
    if "error" in analysis:
        return format_error(f"Analysis failed: {analysis['error']}")

    analysis_id = analysis.get("analysis_id")
    if not analysis_id:
        return format_error("Analysis did not return an analysis_id.")

    reflection = await reflection_client.reflect(analysis_id)
    elapsed_ms = int((time.monotonic() - start) * 1000)
    logger.info(
        "reflect user=%d elapsed=%dms success=%s",
        user_id,
        elapsed_ms,
        "error" not in reflection,
    )
    return format_reflection(reflection)
