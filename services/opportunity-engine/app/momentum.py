"""
Momentum: per-market deltas between consecutive scans.

The platform scans hourly and snapshots each surviving market, which lets it
compute something Kalshi doesn't expose — how markets are *moving*:

  volume_delta     contracts traded since the previous scan
  price_delta      mid-price change in cents (signed)
  spread_delta     bid/ask spread change in cents (signed; negative = tightening)
  liquidity_delta  open-interest change (signed)
  rank_delta       priority-rank improvement (computed post-scoring in scheduler)

Deltas are normalized into [0, 1] momentum scores that feed the Market
Interest Score alongside the state-based factors in scorer.py.
"""

from typing import Optional

from app.config import Settings


def _mid_price(entry: dict) -> Optional[float]:
    """Mid price in cents from a market dict or snapshot row."""
    bid = entry.get("yes_bid")
    ask = entry.get("yes_ask")
    if bid and ask:
        return (bid + ask) / 2.0
    return None


def compute_momentum_factors(
    market: dict,
    previous: Optional[dict],
    settings: Settings,
) -> dict:
    """
    Compare a market against its previous snapshot.

    Returns a dict with raw deltas (for inspection/views) and normalized
    momentum scores in [0, 1] (for scoring).  With no previous snapshot
    (first scan, or a market newly entering the gate), all momentum scores
    are 0.0 and deltas are None — scoring degrades to state-only.
    """
    if previous is None:
        return {
            "volume_delta": None,
            "price_delta": None,
            "spread_delta": None,
            "liquidity_delta": None,
            "volume_momentum": 0.0,
            "price_momentum": 0.0,
            "liquidity_momentum": 0.0,
        }

    volume_delta = max(0, (market.get("volume") or 0) - (previous.get("volume") or 0))

    mid_now = _mid_price(market)
    mid_prev = _mid_price(previous)
    price_delta: Optional[float] = None
    if mid_now is not None and mid_prev is not None:
        price_delta = round(mid_now - mid_prev, 2)

    spread_delta: Optional[int] = None
    bid, ask = market.get("yes_bid"), market.get("yes_ask")
    pbid, pask = previous.get("yes_bid"), previous.get("yes_ask")
    if bid and ask and pbid and pask:
        spread_delta = (ask - bid) - (pask - pbid)

    liquidity_delta = (market.get("open_interest") or 0) - (previous.get("open_interest") or 0)

    def _norm(value: float, normalization: float) -> float:
        if normalization <= 0:
            return 0.0
        return min(abs(value) / normalization, 1.0)

    return {
        "volume_delta": volume_delta,
        "price_delta": price_delta,
        "spread_delta": spread_delta,
        "liquidity_delta": liquidity_delta,
        "volume_momentum": round(_norm(volume_delta, settings.volume_momentum_normalization), 4),
        "price_momentum": round(
            _norm(price_delta, settings.price_momentum_normalization), 4
        ) if price_delta is not None else 0.0,
        "liquidity_momentum": round(
            _norm(max(0, liquidity_delta), settings.liquidity_momentum_normalization), 4
        ),
    }
