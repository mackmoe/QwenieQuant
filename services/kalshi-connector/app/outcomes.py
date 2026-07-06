"""
Outcome collection: polls PostgreSQL for unresolved predictions,
queries Kalshi for resolution status, persists outcomes, and
triggers the Learning Engine (fire-and-forget).
"""

from __future__ import annotations

import asyncio
import logging

import httpx

from app import postgres as postgres_module
from app.client import KalshiClient, KalshiError
from app.config import Settings
from app.markets import get_market

logger = logging.getLogger(__name__)


def _determine_correctness(predicted: str, actual: str) -> bool | None:
    """
    Compare predicted and actual outcome strings (normalised to lowercase).
    Returns None if either value is empty or ambiguous.
    """
    p = predicted.strip().lower()
    a = actual.strip().lower()
    if not p or not a:
        return None
    return p == a


async def _trigger_learning(
    http: httpx.AsyncClient,
    settings: Settings,
    prediction_id: str,
) -> None:
    try:
        resp = await http.post(
            f"{settings.learning_engine_url}/analyze",
            json={},
            timeout=10.0,
        )
        if resp.status_code == 200:
            logger.info("learning_triggered prediction_id=%s", prediction_id)
        else:
            logger.warning(
                "learning_trigger_unexpected_status status=%d prediction_id=%s",
                resp.status_code,
                prediction_id,
            )
    except Exception as exc:
        logger.warning(
            "learning_engine_unavailable prediction_id=%s error=%s — continuing",
            prediction_id,
            exc,
        )


async def run_poll(
    pool,
    client: KalshiClient,
    http: httpx.AsyncClient,
    settings: Settings,
) -> tuple[int, int]:
    """
    One outcome collection cycle.

    1. Query PostgreSQL for unresolved predictions.
    2. For each: query Kalshi for resolution status.
    3. If resolved: persist outcome, trigger Learning Engine.
    4. Return (checked, stored).
    """
    logger.info("outcome_poll_started")

    unresolved = await postgres_module.get_unresolved_predictions(pool)
    logger.info("outcome_poll_unresolved_found count=%d", len(unresolved))

    checked = 0
    stored = 0

    for pred in unresolved:
        prediction_id = pred["prediction_id"]
        market_id = pred["market_id"]
        predicted_value = pred.get("predicted_value") or ""

        logger.info(
            "outcome_checking prediction_id=%s market_id=%s",
            prediction_id,
            market_id,
        )
        checked += 1

        try:
            market = await get_market(client, market_id)
        except KalshiError as exc:
            logger.warning(
                "outcome_kalshi_error prediction_id=%s market_id=%s error=%s — skipping",
                prediction_id,
                market_id,
                exc,
            )
            continue

        if market.result is None:
            logger.info("outcome_market_open market_id=%s — skipping", market_id)
            continue

        actual_value = market.result
        prediction_correct = _determine_correctness(predicted_value, actual_value)

        logger.info(
            "outcome_market_resolved market_id=%s result=%s predicted=%r correct=%s",
            market_id,
            actual_value,
            predicted_value,
            prediction_correct,
        )

        inserted = await postgres_module.persist_outcome(
            pool,
            prediction_id=prediction_id,
            market_id=market_id,
            predicted_value=predicted_value,
            actual_value=actual_value,
            prediction_correct=prediction_correct,
            market_close_time=market.close_time,
            metadata={
                "question": pred.get("question", ""),
                "confidence": float(pred.get("confidence") or 0.0),
            },
        )

        if inserted:
            stored += 1
            logger.info("outcome_stored prediction_id=%s", prediction_id)
            asyncio.create_task(_trigger_learning(http, settings, prediction_id))
        else:
            logger.info(
                "outcome_already_exists prediction_id=%s — skipped", prediction_id
            )

    logger.info("outcome_poll_complete checked=%d stored=%d", checked, stored)
    return checked, stored


async def outcome_loop(
    pool,
    client: KalshiClient,
    http: httpx.AsyncClient,
    settings: Settings,
) -> None:
    """
    Periodic outcome collection loop.  Starts with an initial sleep so the
    first poll does not compete with service startup.
    """
    logger.info(
        "Outcome collection starting; first poll in %ds (enabled=%s)",
        settings.outcome_poll_seconds,
        settings.outcome_collection_enabled,
    )
    await asyncio.sleep(settings.outcome_poll_seconds)
    while True:
        if settings.outcome_collection_enabled and pool is not None:
            try:
                await run_poll(pool, client, http, settings)
            except Exception:
                logger.exception("outcome poll error")
        await asyncio.sleep(settings.outcome_poll_seconds)
