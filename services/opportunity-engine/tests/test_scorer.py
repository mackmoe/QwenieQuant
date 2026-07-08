"""
Tests for deterministic scoring and tier assignment.
No network calls, no mocks needed.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.config import Settings
from app.scorer import (
    _time_score,
    assign_tiers,
    run_scoring,
    score_all,
    score_market,
)
from app.models import ScoredMarket


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _settings(**overrides) -> Settings:
    defaults = dict(
        discovery_interval_seconds=300,
        max_tier2_markets=10,
        max_tier3_markets=3,
        min_priority_score=5.0,
        volume_normalization=10_000.0,
        liquidity_normalization=5_000.0,
        spread_normalization=30.0,
        weight_time=0.30,
        weight_volume=0.25,
        weight_spread=0.20,
        weight_liquidity=0.15,
        weight_activity=0.10,
        kalshi_connector_url="http://mock",
        kalshi_market_limit=1000,
        postgres_url="",
        http_timeout=30.0,
        supported_categories="weather,sports,politics,finance",
    )
    defaults.update(overrides)
    return Settings(**defaults)


def _now() -> datetime:
    return datetime(2026, 7, 6, 12, 0, 0, tzinfo=timezone.utc)


def _market(
    *,
    ticker: str = "TEST-001",
    status: str = "active",
    yes_bid: int | None = 45,
    yes_ask: int | None = 55,
    volume: int = 500,
    open_interest: int = 1000,
    close_time: datetime | None = None,
) -> dict:
    if close_time is None:
        close_time = _now() + timedelta(days=5)
    return {
        "ticker": ticker,
        "title": f"Market {ticker}",
        "status": status,
        "yes_bid": yes_bid,
        "yes_ask": yes_ask,
        "no_bid": 45,
        "no_ask": 55,
        "volume": volume,
        "open_interest": open_interest,
        "close_time": close_time,
        "result": None,
    }


# ---------------------------------------------------------------------------
# _time_score
# ---------------------------------------------------------------------------


def test_time_score_expired():
    assert _time_score(-1) == 0.0


def test_time_score_within_hours():
    assert _time_score(0.3) == 0.20


def test_time_score_today():
    s = _time_score(0.9)
    assert s == 0.50


def test_time_score_sweet_spot_3_days():
    assert _time_score(3) == 1.00


def test_time_score_sweet_spot_7_days():
    assert _time_score(7) == 1.00


def test_time_score_14_days():
    assert _time_score(14) == 0.85


def test_time_score_30_days_is_between_55_and_85():
    s = _time_score(30)
    assert 0.55 <= s <= 0.85


def test_time_score_90_days():
    # 90 days → bottom of the 30–90 range → should be ~0.25
    s = _time_score(90)
    assert 0.20 <= s <= 0.30


def test_time_score_very_far_out():
    assert _time_score(200) == 0.15


def test_time_score_none_returns_low_nonzero():
    s = _time_score(None)
    assert 0 < s < 0.5


def test_time_score_monotone_decreasing_after_sweet_spot():
    scores = [_time_score(d) for d in [7, 14, 30, 60, 90, 180]]
    assert scores == sorted(scores, reverse=True)


# ---------------------------------------------------------------------------
# score_market
# ---------------------------------------------------------------------------


def test_inactive_market_scores_zero():
    m = _market(status="closed")
    score, factors = score_market(m, _now(), _settings())
    assert score == 0.0
    assert factors.get("status") == "inactive"


def test_active_market_scores_positive():
    score, _ = score_market(_market(), _now(), _settings())
    assert score > 0.0


def test_score_is_in_range_0_to_100():
    score, _ = score_market(_market(), _now(), _settings())
    assert 0.0 <= score <= 100.0


def test_high_volume_scores_higher_than_zero_volume():
    high = _market(volume=5_000)
    low = _market(volume=0)
    s_high, _ = score_market(high, _now(), _settings())
    s_low, _ = score_market(low, _now(), _settings())
    assert s_high > s_low


def test_tight_spread_scores_higher_than_wide_spread():
    tight = _market(yes_bid=49, yes_ask=51)   # spread = 2
    wide = _market(yes_bid=20, yes_ask=80)    # spread = 60
    s_tight, _ = score_market(tight, _now(), _settings())
    s_wide, _ = score_market(wide, _now(), _settings())
    assert s_tight > s_wide


def test_market_without_prices_has_zero_activity():
    m = _market(yes_bid=None, yes_ask=None)
    _, factors = score_market(m, _now(), _settings())
    assert factors["activity_score"] == 0.0
    assert factors["spread_score"] == 0.0


def test_sweet_spot_expiry_scores_higher_than_far_out():
    sweet = _market(close_time=_now() + timedelta(days=5))
    far = _market(close_time=_now() + timedelta(days=180))
    s_sweet, _ = score_market(sweet, _now(), _settings())
    s_far, _ = score_market(far, _now(), _settings())
    assert s_sweet > s_far


def test_expired_market_has_zero_time_score():
    m = _market(close_time=_now() - timedelta(days=1))
    _, factors = score_market(m, _now(), _settings())
    assert factors["time_score"] == 0.0


def test_factors_dict_contains_expected_keys():
    _, factors = score_market(_market(), _now(), _settings())
    for key in ("time_score", "volume_score", "spread_score", "liquidity_score", "activity_score"):
        assert key in factors, f"Missing factor: {key}"


def test_score_is_deterministic():
    m = _market()
    s = _settings()
    now = _now()
    s1, _ = score_market(m, now, s)
    s2, _ = score_market(m, now, s)
    assert s1 == s2


def test_market_without_close_time_scores_nonzero():
    m = {**_market(), "close_time": None}
    score, factors = score_market(m, _now(), _settings())
    assert score > 0.0
    assert factors["days_remaining"] is None


# ---------------------------------------------------------------------------
# score_all
# ---------------------------------------------------------------------------


def test_score_all_returns_scored_market_objects():
    markets = [_market(ticker=f"T{i}") for i in range(5)]
    result = score_all(markets, _now(), _settings())
    assert len(result) == 5
    assert all(isinstance(m, ScoredMarket) for m in result)


def test_score_all_skips_empty_ticker():
    markets = [_market(ticker=""), _market(ticker="VALID-001")]
    result = score_all(markets, _now(), _settings())
    assert len(result) == 1
    assert result[0].ticker == "VALID-001"


def test_score_all_returns_unsorted():
    """score_all itself doesn't sort; assign_tiers does."""
    markets = [_market(ticker=f"T{i}", volume=i * 100) for i in range(5)]
    result = score_all(markets, _now(), _settings())
    tickers = [m.ticker for m in result]
    assert tickers == ["T0", "T1", "T2", "T3", "T4"]


# ---------------------------------------------------------------------------
# assign_tiers
# ---------------------------------------------------------------------------


def _make_scored(ticker: str, score: float) -> ScoredMarket:
    return ScoredMarket(
        market_id=ticker,
        ticker=ticker,
        title=ticker,
        priority_score=score,
        assigned_tier=0,
        scoring_timestamp=_now(),
        metadata={},
    )


def test_assign_tiers_top_markets_get_tier3():
    markets = [_make_scored(f"T{i}", float(100 - i)) for i in range(20)]
    result = assign_tiers(markets, min_priority_score=5.0, max_tier2_markets=10, max_tier3_markets=3)
    tier3 = [m for m in result if m.assigned_tier == 3]
    assert len(tier3) == 3


def test_assign_tiers_next_markets_get_tier2():
    markets = [_make_scored(f"T{i}", float(100 - i)) for i in range(20)]
    result = assign_tiers(markets, min_priority_score=5.0, max_tier2_markets=10, max_tier3_markets=3)
    tier2 = [m for m in result if m.assigned_tier == 2]
    assert len(tier2) == 7  # 10 total tier2/3, 3 are tier3


def test_assign_tiers_remainder_get_tier1():
    markets = [_make_scored(f"T{i}", float(100 - i)) for i in range(20)]
    result = assign_tiers(markets, min_priority_score=5.0, max_tier2_markets=10, max_tier3_markets=3)
    tier1 = [m for m in result if m.assigned_tier == 1]
    assert len(tier1) == 10


def test_assign_tiers_zero_score_gets_tier0():
    markets = [_make_scored("INACTIVE", 0.0)]
    result = assign_tiers(markets, min_priority_score=5.0, max_tier2_markets=10, max_tier3_markets=3)
    assert result[0].assigned_tier == 0


def test_assign_tiers_below_min_score_gets_tier1():
    markets = [_make_scored("LOW", 2.0)]  # below min_priority_score=5.0
    result = assign_tiers(markets, min_priority_score=5.0, max_tier2_markets=10, max_tier3_markets=3)
    assert result[0].assigned_tier == 1


def test_assign_tiers_result_sorted_descending():
    import random
    markets = [_make_scored(f"T{i}", float(random.randint(1, 100))) for i in range(10)]
    result = assign_tiers(markets, min_priority_score=5.0, max_tier2_markets=5, max_tier3_markets=2)
    scores = [m.priority_score for m in result]
    assert scores == sorted(scores, reverse=True)


def test_assign_tiers_tier3_is_subset_of_tier2_range():
    """Tier 3 markets should be the highest-scored ones."""
    markets = [_make_scored(f"T{i}", float(100 - i)) for i in range(15)]
    result = assign_tiers(markets, min_priority_score=5.0, max_tier2_markets=8, max_tier3_markets=3)
    tier3_scores = sorted([m.priority_score for m in result if m.assigned_tier == 3], reverse=True)
    tier2_scores = sorted([m.priority_score for m in result if m.assigned_tier == 2], reverse=True)
    # Every tier3 score should be >= every tier2 score
    if tier3_scores and tier2_scores:
        assert min(tier3_scores) >= max(tier2_scores)


# ---------------------------------------------------------------------------
# run_scoring (integration of score_all + assign_tiers)
# ---------------------------------------------------------------------------


def test_run_scoring_returns_sorted_list():
    markets = [_market(ticker=f"T{i}", volume=i * 200) for i in range(10)]
    result = run_scoring(markets, _settings())
    scores = [m.priority_score for m in result]
    assert scores == sorted(scores, reverse=True)


def test_run_scoring_assigns_tiers_to_all():
    markets = [_market(ticker=f"T{i}") for i in range(5)]
    result = run_scoring(markets, _settings())
    assert all(m.assigned_tier in (0, 1, 2, 3) for m in result)


def test_run_scoring_empty_input():
    result = run_scoring([], _settings())
    assert result == []


def test_run_scoring_inactive_markets_get_tier0():
    markets = [_market(ticker="CLOSED", status="closed")]
    result = run_scoring(markets, _settings())
    assert result[0].assigned_tier == 0


def test_run_scoring_ranking_order():
    """Higher-volume active markets rank above lower-volume ones."""
    markets = [
        _market(ticker="LOW", volume=0),
        _market(ticker="HIGH", volume=5_000),
    ]
    result = run_scoring(markets, _settings())
    assert result[0].ticker == "HIGH"
    assert result[1].ticker == "LOW"


def test_score_market_accepts_open_status():
    # Kalshi renamed market status from "active" to "open" in their API.
    # Both values must produce a non-zero score so markets are not silently
    # filtered out after the migration.
    market_open = _market(status="open")
    s = _settings()
    score, _ = score_market(market_open, _now(), s)
    assert score > 0.0


def test_score_market_rejects_unknown_status():
    market_unknown = _market(status="settled")
    s = _settings()
    score, factors = score_market(market_unknown, _now(), s)
    assert score == 0.0
    assert factors.get("status") == "inactive"


# ---------------------------------------------------------------------------
# score_all — Kalshi category/event/series join (Category → Series → Event → Market)
# ---------------------------------------------------------------------------


def test_score_all_attaches_category_from_events():
    markets = [{**_market(ticker="T1"), "event_ticker": "EV1"}]
    events = {"EV1": {"event_ticker": "EV1", "series_ticker": "KXMLB", "category": "Sports"}}
    result = score_all(markets, _now(), _settings(), events_by_ticker=events)
    assert result[0].metadata["category"] == "Sports"
    assert result[0].metadata["series_ticker"] == "KXMLB"
    assert result[0].metadata["event_ticker"] == "EV1"


def test_score_all_no_category_when_event_unknown():
    markets = [{**_market(ticker="T1"), "event_ticker": "MISSING"}]
    result = score_all(markets, _now(), _settings(), events_by_ticker={})
    assert "category" not in result[0].metadata
    assert result[0].metadata["event_ticker"] == "MISSING"


def test_score_all_no_event_fields_when_market_lacks_event_ticker():
    markets = [_market(ticker="T1")]
    result = score_all(markets, _now(), _settings(), events_by_ticker={})
    assert "event_ticker" not in result[0].metadata
    assert "category" not in result[0].metadata


def test_score_all_backward_compatible_without_events_arg():
    markets = [{**_market(ticker="T1"), "event_ticker": "EV1"}]
    result = score_all(markets, _now(), _settings())
    assert result[0].metadata["event_ticker"] == "EV1"
    assert "category" not in result[0].metadata


def test_mve_market_excluded_from_scoring():
    m = {**_market(), "mve_collection_ticker": "KXMVECROSSCATEGORY"}
    score, factors = score_market(m, _now(), _settings())
    assert score == 0.0
    assert factors["status"] == "mve_excluded"


def test_non_mve_market_scores_normally():
    m = {**_market(), "mve_collection_ticker": None}
    score, _ = score_market(m, _now(), _settings())
    assert score > 0.0
