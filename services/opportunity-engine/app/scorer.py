"""
Deterministic market scoring and tier assignment.

No AI, no machine learning, no external calls.
Every score is a pure function of the market's observable attributes.
"""

import math
from datetime import datetime, timezone
from typing import Optional

from app.config import Settings
from app.models import ScoredMarket


# ---------------------------------------------------------------------------
# Time-to-expiration scoring
# ---------------------------------------------------------------------------


def _time_score(days: Optional[float]) -> float:
    """
    Returns 0.0–1.0 based on days until market expiration.

    Sweet spot is 1–7 days: urgent enough to analyze, enough time to act.
    Very recent (< 12 hours) markets may resolve before a trade can execute.
    Very distant (> 90 days) markets are lower priority than imminent ones.
    """
    if days is None:
        return 0.10  # unknown expiry — low but non-zero
    if days < 0:
        return 0.00  # already expired
    if days < 0.5:
        return 0.20  # expiring within hours — likely too late
    if days <= 1:
        return 0.50  # expiring today — possible but tight
    if days <= 7:
        return 1.00  # sweet spot
    if days <= 14:
        return 0.85
    if days <= 30:
        # linear decay from 0.85 to 0.55
        return 0.85 - 0.30 * (days - 14) / 16
    if days <= 90:
        # linear decay from 0.55 to 0.25
        return 0.55 - 0.30 * (days - 30) / 60
    return 0.15  # very far out


# ---------------------------------------------------------------------------
# Single-market scoring
# ---------------------------------------------------------------------------


def score_market(
    market: dict,
    now: datetime,
    settings: Settings,
) -> tuple[float, dict]:
    """
    Return (priority_score, factors) for one market.

    priority_score is in [0.0, 100.0].  Higher is better.
    factors is a dict of per-component scores for inspection/debugging.

    Returns (0.0, {}) for inactive or malformed markets.
    """
    # Gate: only active/open markets are worth scoring.
    # Kalshi renamed the status value from "active" to "open" in their API;
    # accept both so scoring survives the migration in either direction.
    if market.get("status") not in ("active", "open"):
        return 0.0, {"status": "inactive"}

    # Gate: exclude MVE (multivariate/parlay) markets — Kalshi's auto-generated
    # combination contracts.  Their titles aggregate several outcomes and their
    # synthetic events carry no category; the workflow skips them anyway.
    if market.get("mve_collection_ticker"):
        return 0.0, {"status": "mve_excluded"}

    factors: dict = {}

    # ── Time to expiration ────────────────────────────────────────────────
    raw_close = market.get("close_time")
    days_remaining: Optional[float] = None
    if raw_close is not None:
        if isinstance(raw_close, datetime):
            close_dt = raw_close
        else:
            try:
                close_dt = datetime.fromisoformat(str(raw_close).replace("Z", "+00:00"))
            except (ValueError, TypeError):
                close_dt = None
        if close_dt is not None:
            if close_dt.tzinfo is None:
                close_dt = close_dt.replace(tzinfo=timezone.utc)
            days_remaining = (close_dt - now).total_seconds() / 86400
    time_f = _time_score(days_remaining)
    factors["days_remaining"] = round(days_remaining, 2) if days_remaining is not None else None
    factors["time_score"] = round(time_f, 4)

    # ── Volume ────────────────────────────────────────────────────────────
    volume = max(0, market.get("volume") or 0)
    if settings.volume_normalization > 0:
        volume_f = math.log1p(volume) / math.log1p(settings.volume_normalization)
        volume_f = min(volume_f, 1.0)
    else:
        volume_f = 0.0
    factors["volume"] = volume
    factors["volume_score"] = round(volume_f, 4)

    # ── Spread (tighter = better, indicates active market) ────────────────
    yes_bid = market.get("yes_bid") or 0
    yes_ask = market.get("yes_ask") or 0
    if yes_bid > 0 and yes_ask > 0 and yes_ask >= yes_bid:
        spread = yes_ask - yes_bid
        spread_f = max(0.0, 1.0 - spread / settings.spread_normalization)
    else:
        spread_f = 0.0
        spread = None
    factors["spread"] = spread
    factors["spread_score"] = round(spread_f, 4)

    # ── Liquidity (open interest) ─────────────────────────────────────────
    oi = max(0, market.get("open_interest") or 0)
    liquidity_f = min(oi / settings.liquidity_normalization, 1.0) if settings.liquidity_normalization > 0 else 0.0
    factors["open_interest"] = oi
    factors["liquidity_score"] = round(liquidity_f, 4)

    # ── Activity (has bid/ask at all) ─────────────────────────────────────
    activity_f = 1.0 if (yes_bid > 0 and yes_ask > 0) else 0.0
    factors["activity_score"] = activity_f

    # ── Weighted sum, normalized so score ∈ [0, 100] ─────────────────────
    weight_total = (
        settings.weight_time
        + settings.weight_volume
        + settings.weight_spread
        + settings.weight_liquidity
        + settings.weight_activity
    )
    if weight_total <= 0:
        return 0.0, factors

    raw = (
        settings.weight_time * time_f
        + settings.weight_volume * volume_f
        + settings.weight_spread * spread_f
        + settings.weight_liquidity * liquidity_f
        + settings.weight_activity * activity_f
    )
    score = (raw / weight_total) * 100.0
    factors["raw_weighted"] = round(raw, 4)

    return round(score, 4), factors


# ---------------------------------------------------------------------------
# Batch scoring
# ---------------------------------------------------------------------------


def score_all(
    markets: list[dict],
    now: datetime,
    settings: Settings,
    events_by_ticker: Optional[dict] = None,
) -> list[ScoredMarket]:
    """
    Score every market and return unsorted ScoredMarket objects.

    events_by_ticker maps event_ticker → event dict; when provided, each
    market's metadata gains Kalshi's category / series_ticker / event_ticker
    (hierarchy: Category → Series → Event → Market).
    """
    events_by_ticker = events_by_ticker or {}
    results: list[ScoredMarket] = []
    for m in markets:
        ticker = m.get("ticker", "")
        if not ticker:
            continue
        score, factors = score_market(m, now, settings)
        event_ticker = m.get("event_ticker")
        if event_ticker:
            factors["event_ticker"] = event_ticker
            event = events_by_ticker.get(event_ticker)
            if event:
                if event.get("category"):
                    factors["category"] = event["category"]
                if event.get("series_ticker"):
                    factors["series_ticker"] = event["series_ticker"]
        results.append(
            ScoredMarket(
                market_id=ticker,
                ticker=ticker,
                title=m.get("title", ""),
                priority_score=score,
                assigned_tier=0,        # placeholder; set by assign_tiers
                scoring_timestamp=now,
                metadata=factors,
            )
        )
    return results


# ---------------------------------------------------------------------------
# Tier assignment
# ---------------------------------------------------------------------------


def assign_tiers(
    markets: list[ScoredMarket],
    min_priority_score: float,
    max_tier2_markets: int,
    max_tier3_markets: int,
) -> list[ScoredMarket]:
    """
    Assign each market its highest qualifying tier.

    Tier 0  — score == 0 (inactive or unquoteable)
    Tier 1  — score > 0 (basic filter passed)
    Tier 2  — top max_tier2_markets markets above min_priority_score
    Tier 3  — top max_tier3_markets markets (subset of tier 2)

    Returns a new list sorted by priority_score descending.
    """
    sorted_m = sorted(markets, key=lambda m: m.priority_score, reverse=True)

    result: list[ScoredMarket] = []
    tier3_count = 0
    tier2_count = 0

    for m in sorted_m:
        if m.priority_score <= 0.0:
            tier = 0
        elif m.priority_score < min_priority_score:
            tier = 1
        elif tier3_count < max_tier3_markets:
            tier = 3
            tier3_count += 1
            tier2_count += 1
        elif tier2_count < max_tier2_markets:
            tier = 2
            tier2_count += 1
        else:
            tier = 1

        result.append(m.model_copy(update={"assigned_tier": tier}))

    return result


# ---------------------------------------------------------------------------
# Convenience: score + tier in one call
# ---------------------------------------------------------------------------


def run_scoring(
    markets: list[dict],
    settings: Settings,
    now: Optional[datetime] = None,
    events_by_ticker: Optional[dict] = None,
) -> list[ScoredMarket]:
    """Score all markets and assign tiers. Returns sorted list."""
    if now is None:
        now = datetime.now(timezone.utc)
    scored = score_all(markets, now, settings, events_by_ticker=events_by_ticker)
    return assign_tiers(
        scored,
        min_priority_score=settings.min_priority_score,
        max_tier2_markets=settings.max_tier2_markets,
        max_tier3_markets=settings.max_tier3_markets,
    )
