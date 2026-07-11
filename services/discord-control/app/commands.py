"""
Command handler functions — pure async logic with no Discord coupling.

Each handler receives clients and settings as arguments and returns a
formatted string ready to send as a Discord message. discord_bot.py
wires these to slash commands and enforces authorization.

Keeping business logic here (instead of in discord_bot.py) makes every
handler unit-testable without Discord objects.
"""

import asyncio
import logging
import time

from app.clients import OpportunityClient, PredictionClient, LearningClient, PredictionQueueClient, ReflectionClient, RiskManagerClient
from app.config import Settings
from app.formatter import (
    UNAUTHORIZED_MESSAGE,
    format_analysis,
    format_activity,
    format_brief,
    format_error,
    format_hot,
    format_markets,
    format_performance,
    format_prediction,
    format_reflection,
    format_run,
    format_scan,
    format_status,
    format_workflow,
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


async def handle_markets(
    user_id: int,
    opportunity_client: OpportunityClient,
    category: str | None = None,
    limit: int = 10,
) -> str:
    start = time.monotonic()
    result = await opportunity_client.get_opportunities(limit=limit)
    elapsed_ms = int((time.monotonic() - start) * 1000)
    logger.info(
        "markets user=%d category=%s limit=%d elapsed=%dms",
        user_id,
        category or "all",
        limit,
        elapsed_ms,
    )
    return format_markets(result, category=category)


async def handle_hot(
    user_id: int,
    opportunity_client: OpportunityClient,
    limit: int = 3,
) -> str:
    """Market Interest views: most active, fastest rising, liquidity, top MIS."""
    start = time.monotonic()
    views = await opportunity_client.get_views(limit=limit)
    elapsed_ms = int((time.monotonic() - start) * 1000)
    logger.info("hot user=%d limit=%d elapsed=%dms", user_id, limit, elapsed_ms)
    return format_hot(views)


async def handle_workflow(
    user_id: int,
    opportunity_client: OpportunityClient,
    queue_client: PredictionQueueClient,
    learning_client: LearningClient,
    reflection_client: ReflectionClient,
    prediction_client: PredictionClient,
) -> str:
    start = time.monotonic()
    results = await asyncio.gather(
        opportunity_client.health(),
        queue_client.health(),
        queue_client.get_stats(),
        learning_client.health(),
        reflection_client.health(),
        prediction_client.health(),
        return_exceptions=True,
    )
    oe_health, pq_health, pq_stats, le_health, re_health, pred_health = results

    def _safe(r):
        return r if isinstance(r, dict) else {"error": str(r)}

    elapsed_ms = int((time.monotonic() - start) * 1000)
    logger.info("workflow user=%d elapsed=%dms", user_id, elapsed_ms)
    return format_workflow(
        oe_health=_safe(oe_health),
        pq_health=_safe(pq_health),
        pq_stats=_safe(pq_stats),
        le_health=_safe(le_health),
        re_health=_safe(re_health),
        pred_health=_safe(pred_health),
    )


async def handle_performance(
    user_id: int,
    learning_client: LearningClient,
    settings: Settings,
) -> str:
    start = time.monotonic()
    analysis = await learning_client.analyze()
    elapsed_ms = int((time.monotonic() - start) * 1000)
    logger.info(
        "performance user=%d elapsed=%dms success=%s",
        user_id,
        elapsed_ms,
        "error" not in analysis,
    )
    return format_performance(analysis, settings)


async def handle_activity(
    user_id: int,
    queue_client: PredictionQueueClient,
    opportunity_client: OpportunityClient,
    limit: int = 25,
) -> str:
    start = time.monotonic()
    results = await asyncio.gather(
        queue_client.get_recent_completed(limit=limit),
        opportunity_client.health(),
        return_exceptions=True,
    )
    completed, oe_health = results

    def _safe(r):
        return r if isinstance(r, dict) else {"error": str(r)}

    elapsed_ms = int((time.monotonic() - start) * 1000)
    logger.info("activity user=%d elapsed=%dms", user_id, elapsed_ms)
    return format_activity(_safe(completed), _safe(oe_health))


async def handle_scan(
    user_id: int,
    opportunity_client: OpportunityClient,
) -> str:
    start = time.monotonic()
    result = await opportunity_client.refresh()
    elapsed_ms = int((time.monotonic() - start) * 1000)
    success = "error" not in result
    logger.info(
        "scan user=%d elapsed=%dms success=%s",
        user_id,
        elapsed_ms,
        success,
    )
    return format_scan(result)


async def handle_brief(
    user_id: int,
    opportunity_client: OpportunityClient,
    queue_client: PredictionQueueClient,
    learning_client: LearningClient,
    reflection_client: ReflectionClient,
    prediction_client: PredictionClient,
    risk_manager_client: RiskManagerClient,
    settings: Settings,
    uptime_seconds: float,
) -> str:
    start = time.monotonic()

    results = await asyncio.gather(
        opportunity_client.health(),
        queue_client.health(),
        queue_client.get_stats(),
        learning_client.analyze(),
        prediction_client.health(),
        risk_manager_client.health(),
        opportunity_client.get_opportunities(limit=1),
        queue_client.get_activity_stats(),
        opportunity_client.get_best_by_category(),
        return_exceptions=True,
    )

    def _safe(r):
        return r if isinstance(r, dict) else {"error": str(r)}

    (oe_health, pq_health, pq_stats, analysis,
     pred_health, rm_health, top_opps, activity, by_category) = [_safe(r) for r in results]

    # Sequential: reflect only if analyze returned a valid analysis_id.
    # The reflection engine is rule-based (no LLM), so this is fast.
    reflection: dict = {"error": "no analysis available"}
    if "error" not in analysis and analysis.get("analysis_id"):
        reflection = await reflection_client.reflect(analysis["analysis_id"])
        if not isinstance(reflection, dict):
            reflection = {"error": "unexpected response"}

    elapsed_ms = int((time.monotonic() - start) * 1000)
    logger.info("brief user=%d elapsed=%dms", user_id, elapsed_ms)

    return format_brief(
        oe_health=oe_health,
        pq_health=pq_health,
        pq_stats=pq_stats,
        analysis=analysis,
        pred_health=pred_health,
        rm_health=rm_health,
        top_opps=top_opps,
        reflection=reflection,
        settings=settings,
        uptime_seconds=uptime_seconds,
        activity=activity,
        by_category=by_category,
    )


async def handle_run(
    user_id: int,
    queue_client: PredictionQueueClient,
) -> str:
    start = time.monotonic()
    result = await queue_client.run_workflow()
    elapsed_ms = int((time.monotonic() - start) * 1000)
    logger.info(
        "run user=%d status=%s elapsed=%dms",
        user_id,
        result.get("status", "error"),
        elapsed_ms,
    )
    return format_run(result)


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
