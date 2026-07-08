"""
Tests for scheduler module: run_scan, get_state, _set_state, _tier_counts.
No postgres, no real HTTP — kalshi-connector calls are mocked.
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app import scheduler as sched_module
from app.config import Settings
from app.models import ScoredMarket
from app.scheduler import _set_state, _tier_counts, get_state, run_scan


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _settings(**overrides) -> Settings:
    defaults = dict(
        discovery_interval_seconds=1,
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
        kalshi_connector_url="http://mock-kalshi",
        kalshi_market_limit=100,
        postgres_url="",
        http_timeout=5.0,
        supported_categories="weather,sports",
    )
    defaults.update(overrides)
    return Settings(**defaults)


def _now() -> datetime:
    return datetime(2026, 7, 6, 12, 0, 0, tzinfo=timezone.utc)


def _active_market(ticker: str, days_out: int = 5, volume: int = 500) -> dict:
    from datetime import timedelta

    return {
        "ticker": ticker,
        "title": f"Market {ticker}",
        "status": "active",
        "yes_bid": 45,
        "yes_ask": 55,
        "no_bid": 45,
        "no_ask": 55,
        "volume": volume,
        "open_interest": 1000,
        "close_time": _now() + timedelta(days=days_out),
        "result": None,
    }


def _make_scored(ticker: str, tier: int, score: float = 50.0) -> ScoredMarket:
    return ScoredMarket(
        market_id=ticker,
        ticker=ticker,
        title=ticker,
        priority_score=score,
        assigned_tier=tier,
        scoring_timestamp=_now(),
        metadata={},
    )


@pytest.fixture(autouse=True)
def reset_state():
    """Reset module-level scheduler state before every test."""
    _set_state(None, [])
    yield
    _set_state(None, [])


# ---------------------------------------------------------------------------
# get_state / _set_state
# ---------------------------------------------------------------------------


def test_initial_state_is_empty():
    last_scan, markets = get_state()
    assert last_scan is None
    assert markets == []


def test_set_state_persists():
    ts = _now()
    markets = [_make_scored("T1", 2)]
    _set_state(ts, markets)
    last_scan, result = get_state()
    assert last_scan == ts
    assert len(result) == 1
    assert result[0].ticker == "T1"


def test_get_state_returns_copy():
    ts = _now()
    markets = [_make_scored("T1", 2)]
    _set_state(ts, markets)
    _, result1 = get_state()
    result1.append(_make_scored("T2", 1))
    _, result2 = get_state()
    assert len(result2) == 1  # original unchanged


# ---------------------------------------------------------------------------
# _tier_counts
# ---------------------------------------------------------------------------


def test_tier_counts_empty():
    counts = _tier_counts([])
    assert counts == {"0": 0, "1": 0, "2": 0, "3": 0}


def test_tier_counts_mixed():
    markets = [
        _make_scored("A", 0),
        _make_scored("B", 1),
        _make_scored("C", 1),
        _make_scored("D", 2),
        _make_scored("E", 3),
    ]
    counts = _tier_counts(markets)
    assert counts["0"] == 1
    assert counts["1"] == 2
    assert counts["2"] == 1
    assert counts["3"] == 1


def test_tier_counts_all_same_tier():
    markets = [_make_scored(f"T{i}", 2) for i in range(5)]
    counts = _tier_counts(markets)
    assert counts["2"] == 5
    assert counts["3"] == 0


# ---------------------------------------------------------------------------
# run_scan
# ---------------------------------------------------------------------------


async def test_run_scan_returns_scored_markets_and_duration():
    raw = [_active_market(f"T{i}") for i in range(5)]
    mock_http = MagicMock(spec=httpx.AsyncClient)

    with patch("app.scheduler.KalshiConnectorClient") as MockKC:
        instance = MockKC.return_value
        instance.get_markets = AsyncMock(return_value=raw)
        instance.get_events = AsyncMock(return_value=[])

        tiered, duration_ms = await run_scan(mock_http, _settings())

    assert len(tiered) == 5
    assert duration_ms >= 0


async def test_run_scan_updates_module_state():
    raw = [_active_market("X1"), _active_market("X2")]
    mock_http = MagicMock(spec=httpx.AsyncClient)

    with patch("app.scheduler.KalshiConnectorClient") as MockKC:
        instance = MockKC.return_value
        instance.get_markets = AsyncMock(return_value=raw)
        instance.get_events = AsyncMock(return_value=[])

        await run_scan(mock_http, _settings())

    last_scan, markets = get_state()
    assert last_scan is not None
    assert len(markets) == 2


async def test_run_scan_empty_markets():
    mock_http = MagicMock(spec=httpx.AsyncClient)

    with patch("app.scheduler.KalshiConnectorClient") as MockKC:
        instance = MockKC.return_value
        instance.get_markets = AsyncMock(return_value=[])
        instance.get_events = AsyncMock(return_value=[])

        tiered, duration_ms = await run_scan(mock_http, _settings())

    assert tiered == []
    _, markets = get_state()
    assert markets == []


async def test_run_scan_kalshi_unavailable_returns_empty():
    mock_http = MagicMock(spec=httpx.AsyncClient)

    with patch("app.scheduler.KalshiConnectorClient") as MockKC:
        instance = MockKC.return_value
        instance.get_markets = AsyncMock(return_value=[])
        instance.get_events = AsyncMock(return_value=[])

        tiered, _ = await run_scan(mock_http, _settings())

    assert tiered == []


async def test_run_scan_without_pool_skips_postgres():
    raw = [_active_market("P1")]
    mock_http = MagicMock(spec=httpx.AsyncClient)

    with patch("app.scheduler.KalshiConnectorClient") as MockKC:
        instance = MockKC.return_value
        instance.get_markets = AsyncMock(return_value=raw)
        instance.get_events = AsyncMock(return_value=[])

        with patch("app.postgres.upsert_scores", new_callable=AsyncMock) as mock_upsert:
            tiered, _ = await run_scan(mock_http, _settings(), pool=None)
            mock_upsert.assert_not_called()

    assert len(tiered) == 1


async def test_run_scan_with_pool_calls_upsert():
    raw = [_active_market("P1")]
    mock_http = MagicMock(spec=httpx.AsyncClient)
    mock_pool = MagicMock()

    with patch("app.scheduler.KalshiConnectorClient") as MockKC:
        instance = MockKC.return_value
        instance.get_markets = AsyncMock(return_value=raw)
        instance.get_events = AsyncMock(return_value=[])

        with patch("app.postgres.upsert_scores", new_callable=AsyncMock) as mock_upsert:
            tiered, _ = await run_scan(mock_http, _settings(), pool=mock_pool)
            mock_upsert.assert_called_once()


async def test_run_scan_sorted_descending():
    raw = [
        _active_market("LOW", days_out=5, volume=0),
        _active_market("HIGH", days_out=5, volume=5_000),
    ]
    mock_http = MagicMock(spec=httpx.AsyncClient)

    with patch("app.scheduler.KalshiConnectorClient") as MockKC:
        instance = MockKC.return_value
        instance.get_markets = AsyncMock(return_value=raw)
        instance.get_events = AsyncMock(return_value=[])

        tiered, _ = await run_scan(mock_http, _settings())

    scores = [m.priority_score for m in tiered]
    assert scores == sorted(scores, reverse=True)


async def test_run_scan_overwrites_previous_state():
    mock_http = MagicMock(spec=httpx.AsyncClient)

    with patch("app.scheduler.KalshiConnectorClient") as MockKC:
        instance = MockKC.return_value
        instance.get_markets = AsyncMock(return_value=[_active_market("FIRST")])
        instance.get_events = AsyncMock(return_value=[])
        with patch("app.queue_publisher.publish_opportunities", new_callable=AsyncMock):
            await run_scan(mock_http, _settings())

        _, markets_after_first = get_state()
        assert len(markets_after_first) == 1

        instance.get_markets = AsyncMock(return_value=[_active_market("A"), _active_market("B")])
        instance.get_events = AsyncMock(return_value=[])
        with patch("app.queue_publisher.publish_opportunities", new_callable=AsyncMock):
            await run_scan(mock_http, _settings())

    _, markets_after_second = get_state()
    assert len(markets_after_second) == 2


# ---------------------------------------------------------------------------
# run_scan — queue publishing integration
# ---------------------------------------------------------------------------


async def test_run_scan_calls_publish_with_tier3_only():
    raw = [_active_market(f"T{i}", days_out=5, volume=5_000) for i in range(5)]
    mock_http = MagicMock(spec=httpx.AsyncClient)

    with patch("app.scheduler.KalshiConnectorClient") as MockKC:
        instance = MockKC.return_value
        instance.get_markets = AsyncMock(return_value=raw)
        instance.get_events = AsyncMock(return_value=[])

        with patch(
            "app.queue_publisher.publish_opportunities", new_callable=AsyncMock
        ) as mock_publish:
            mock_publish.return_value = 3
            await run_scan(mock_http, _settings(max_tier3_markets=3))

    mock_publish.assert_called_once()
    _, _, tier3_arg = mock_publish.call_args[0]
    assert all(m.assigned_tier == 3 for m in tier3_arg)


async def test_run_scan_does_not_publish_tier1_or_tier2():
    raw = [_active_market(f"T{i}", days_out=5, volume=5_000) for i in range(5)]
    mock_http = MagicMock(spec=httpx.AsyncClient)

    with patch("app.scheduler.KalshiConnectorClient") as MockKC:
        instance = MockKC.return_value
        instance.get_markets = AsyncMock(return_value=raw)
        instance.get_events = AsyncMock(return_value=[])

        with patch(
            "app.queue_publisher.publish_opportunities", new_callable=AsyncMock
        ) as mock_publish:
            await run_scan(mock_http, _settings(max_tier3_markets=3))

    _, _, tier3_arg = mock_publish.call_args[0]
    assert not any(m.assigned_tier in (1, 2) for m in tier3_arg)


async def test_run_scan_publish_failure_does_not_stop_scan():
    raw = [_active_market("T1")]
    mock_http = MagicMock(spec=httpx.AsyncClient)

    with patch("app.scheduler.KalshiConnectorClient") as MockKC:
        instance = MockKC.return_value
        instance.get_markets = AsyncMock(return_value=raw)
        instance.get_events = AsyncMock(return_value=[])

        with patch(
            "app.queue_publisher.publish_opportunities",
            new_callable=AsyncMock,
            side_effect=Exception("Queue down"),
        ):
            # run_scan wraps publish in try/except — must not raise
            tiered, duration_ms = await run_scan(mock_http, _settings())

    assert len(tiered) == 1
    _, markets = get_state()
    assert len(markets) == 1


async def test_run_scan_publish_disabled_skips_publish():
    raw = [_active_market("T1")]
    mock_http = MagicMock(spec=httpx.AsyncClient)

    with patch("app.scheduler.KalshiConnectorClient") as MockKC:
        instance = MockKC.return_value
        instance.get_markets = AsyncMock(return_value=raw)
        instance.get_events = AsyncMock(return_value=[])

        with patch(
            "app.queue_publisher.publish_opportunities", new_callable=AsyncMock
        ) as mock_publish:
            await run_scan(mock_http, _settings(publish_to_queue=False))

    # publish_opportunities is still called; it returns early internally
    mock_publish.assert_called_once()


async def test_run_scan_empty_markets_publishes_empty_tier3():
    mock_http = MagicMock(spec=httpx.AsyncClient)

    with patch("app.scheduler.KalshiConnectorClient") as MockKC:
        instance = MockKC.return_value
        instance.get_markets = AsyncMock(return_value=[])
        instance.get_events = AsyncMock(return_value=[])

        with patch(
            "app.queue_publisher.publish_opportunities", new_callable=AsyncMock
        ) as mock_publish:
            mock_publish.return_value = 0
            await run_scan(mock_http, _settings())

    _, _, tier3_arg = mock_publish.call_args[0]
    assert tier3_arg == []
