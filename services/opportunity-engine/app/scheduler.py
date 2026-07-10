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
from app.momentum import compute_momentum_factors
from app.scorer import apply_ingest_gate, run_scoring

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

    # Ingest gate: discard dead markets before scoring/persisting anything.
    gated = apply_ingest_gate(raw_markets, settings)
    logger.info(
        "Ingest gate: %d of %d markets passed (%.0f%% dropped)",
        len(gated),
        len(raw_markets),
        100.0 * (1 - len(gated) / len(raw_markets)) if raw_markets else 0.0,
    )

    # Events carry Kalshi's category + series_ticker for each market
    # (hierarchy: Category → Series → Event → Market).
    raw_events = await client.get_events()
    events_by_ticker = {
        e["event_ticker"]: e for e in raw_events if e.get("event_ticker")
    }

    # Momentum: deltas vs the previous scan's snapshots.
    previous_snapshots: dict = {}
    series_performance: dict = {}
    if pool is not None:
        from app.postgres import fetch_latest_snapshots, fetch_series_performance
        previous_snapshots = await fetch_latest_snapshots(pool)
        # Learning feedback: resolved accuracy per series (trailing window)
        series_performance = await fetch_series_performance(
            pool,
            min_resolved=settings.series_perf_min_resolved,
            window_days=settings.series_perf_window_days,
        )
        if series_performance:
            logger.info(
                "Series feedback loaded: %d series with resolved history",
                len(series_performance),
            )
    momentum_by_ticker = {
        m["ticker"]: compute_momentum_factors(
            m, previous_snapshots.get(m["ticker"]), settings
        )
        for m in gated
        if m.get("ticker")
    }

    now = datetime.now(timezone.utc)
    tiered = run_scoring(
        gated, settings, now=now,
        events_by_ticker=events_by_ticker,
        momentum_by_ticker=momentum_by_ticker,
        series_performance=series_performance,
    )

    # Ranks + rank deltas (run_scoring returns the list sorted by priority).
    raw_by_ticker = {m.get("ticker"): m for m in gated}
    for rank, sm in enumerate(tiered, start=1):
        sm.metadata["rank"] = rank
        prev = previous_snapshots.get(sm.ticker)
        prev_rank = prev.get("rank") if prev else None
        # Positive = climbed the board since the last scan.
        sm.metadata["rank_delta"] = (prev_rank - rank) if prev_rank else None
        raw = raw_by_ticker.get(sm.ticker) or {}
        sm.metadata["yes_bid"] = raw.get("yes_bid")
        sm.metadata["yes_ask"] = raw.get("yes_ask")

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
        from app.postgres import (
            insert_snapshots,
            prune_scores,
            prune_snapshots,
            upsert_scores,
        )
        await upsert_scores(pool, tiered)
        await insert_snapshots(pool, tiered, now)
        await prune_snapshots(pool, settings.snapshot_retention_days)
        await prune_scores(pool, settings.score_retention_days)

    tier3 = [m for m in tiered if m.assigned_tier == 3]
    from app.queue_publisher import publish_opportunities
    try:
        await publish_opportunities(http, settings, tier3)
    except Exception:
        logger.exception("Queue publish failed unexpectedly; scan result retained")

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
