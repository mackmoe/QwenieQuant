"""
Background scheduler: discovers markets, scores them, persists results.

Module-level state is the in-memory cache served by the routes layer.
Tests may inject state directly via _set_state() without running a live scan.
"""

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Optional

import httpx

from app.config import Settings
from app.kalshi_client import KalshiConnectorClient
from app.models import ScoredMarket
from app.scorer import run_scoring

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# In-memory state
# ---------------------------------------------------------------------------

_last_scan: Optional[datetime] = None
_scored_markets: list[ScoredMarket] = []


def get_state() -> tuple[Optional[datetime], list[ScoredMarket]]:
    return _last_scan, list(_scored_markets)


def _set_state(last_scan: Optional[datetime], markets: list[ScoredMarket]) -> None:
    """For testing only."""
    global _last_scan, _scored_markets
    _last_scan = last_scan
    _scored_markets = markets


def _tier_counts(markets: list[ScoredMarket]) -> dict[str, int]:
    counts: dict[str, int] = {"0": 0, "1": 0, "2": 0, "3": 0}
    for m in markets:
        key = str(m.assigned_tier)
        counts[key] = counts.get(key, 0) + 1
    return counts


# ---------------------------------------------------------------------------
# Core scan
# ---------------------------------------------------------------------------


async def run_scan(
    http: httpx.AsyncClient,
    settings: Settings,
    pool=None,
) -> tuple[list[ScoredMarket], int]:
    """
    One complete discovery + scoring pass.

    Returns (scored_markets, duration_ms).
    Updates module-level state on success.
    """
    global _last_scan, _scored_markets

    t0 = time.monotonic()
    client = KalshiConnectorClient(settings.kalshi_connector_url, http)
    raw_markets = await client.get_markets(limit=settings.kalshi_market_limit)

    now = datetime.now(timezone.utc)
    tiered = run_scoring(raw_markets, settings, now=now)

    duration_ms = int((time.monotonic() - t0) * 1000)

    tier_counts = _tier_counts(tiered)
    logger.info(
        "Scan complete: %d total, tier3=%s, tier2=%s, tier1=%s, duration=%dms",
        len(tiered),
        tier_counts.get("3", 0),
        tier_counts.get("2", 0),
        tier_counts.get("1", 0),
        duration_ms,
    )

    _last_scan = now
    _scored_markets = tiered

    if pool is not None:
        from app.postgres import upsert_scores
        await upsert_scores(pool, tiered)

    return tiered, duration_ms


# ---------------------------------------------------------------------------
# Background loop
# ---------------------------------------------------------------------------


async def scheduler_loop(
    http: httpx.AsyncClient,
    settings: Settings,
    pool=None,
) -> None:
    """
    Periodic scoring loop.  Starts with an initial sleep so the first
    scan doesn't compete with lifespan startup.  Call POST /refresh to
    trigger an immediate scan outside the schedule.
    """
    logger.info(
        "Scheduler starting; first scan in %ds", settings.discovery_interval_seconds
    )
    await asyncio.sleep(settings.discovery_interval_seconds)
    while True:
        try:
            await run_scan(http, settings, pool)
        except Exception:
            logger.exception("Scheduled scan failed")
        await asyncio.sleep(settings.discovery_interval_seconds)
