"""
Publishes Tier 3 opportunities to the Prediction Queue via POST /queue/add.

Failures are logged and swallowed — the scheduler must continue running
regardless of whether the Prediction Queue is reachable.
"""

import logging
from typing import Any

import httpx

from app.config import Settings
from app.models import ScoredMarket

logger = logging.getLogger(__name__)


def _build_payload(markets: list[ScoredMarket]) -> dict:
    opportunities = []
    for m in markets:
        opp: dict[str, Any] = {
            "market_id": m.market_id,
            "ticker": m.ticker,
            "priority_score": m.priority_score,
            "metadata": {
                "title": m.title,
                "assigned_tier": m.assigned_tier,
                **m.metadata,
            },
        }
        opportunities.append(opp)
    return {"opportunities": opportunities}


async def publish_opportunities(
    http: httpx.AsyncClient,
    settings: Settings,
    tier3_markets: list[ScoredMarket],
) -> int:
    """
    POST Tier 3 markets to the Prediction Queue.

    Returns the count submitted (batch size, not the queue's added count).
    Returns 0 if publishing is disabled, the batch is empty, or the queue
    is unavailable.  Never raises.
    """
    if not settings.publish_to_queue:
        logger.debug("Queue publishing disabled — skipping")
        return 0

    if not tier3_markets:
        logger.info("No Tier 3 markets to publish")
        return 0

    batch = tier3_markets[: settings.queue_publish_batch_size]
    url = settings.prediction_queue_url.rstrip("/") + "/queue/add"
    payload = _build_payload(batch)

    logger.info("Publishing %d Tier 3 opportunities to Prediction Queue", len(batch))
    try:
        resp = await http.post(url, json=payload, timeout=10.0)
        resp.raise_for_status()
        data = resp.json()
        added = data.get("added", 0)
        updated = data.get("updated", 0)
        logger.info(
            "Successfully published %d opportunities (added=%d updated=%d)",
            len(batch),
            added,
            updated,
        )
        return len(batch)
    except Exception as exc:
        logger.warning(
            "Prediction Queue unavailable: %s — continuing normally", exc
        )
        return 0
