"""
Aggregates health status from all platform services concurrently.

Used by the /status command. Returns a single dict describing the
state of every service the platform depends on.
"""

import asyncio

from app.clients import PredictionClient, LearningClient, ReflectionClient, check_reachable
from app.config import Settings


async def check_all_services(
    prediction_client: PredictionClient,
    learning_client: LearningClient,
    reflection_client: ReflectionClient,
    http,
    settings: Settings,
) -> dict:
    results = await asyncio.gather(
        prediction_client.health(),
        learning_client.health(),
        reflection_client.health(),
        check_reachable(http, f"{settings.ollama_url}/api/tags"),
        check_reachable(http, f"{settings.searxng_url}/healthz"),
        return_exceptions=True,
    )
    pred, learn, reflect, ollama_ok, searxng_ok = results

    if isinstance(pred, Exception):
        pred = {"status": "unreachable"}
    if isinstance(learn, Exception):
        learn = {"status": "unreachable", "postgres": False}
    if isinstance(reflect, Exception):
        reflect = {"status": "unreachable", "postgres": False}

    ollama_ok = not isinstance(ollama_ok, Exception) and ollama_ok is True
    searxng_ok = not isinstance(searxng_ok, Exception) and searxng_ok is True

    return {
        "prediction_api": pred,
        "learning_engine": learn,
        "reflection_engine": reflect,
        "ollama": {"reachable": ollama_ok},
        "searxng": {"reachable": searxng_ok},
    }
