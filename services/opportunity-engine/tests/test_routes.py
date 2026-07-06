"""
Tests for HTTP routes (GET /health, GET /opportunities, GET /opportunities/top, POST /refresh).
Uses TestClient with lifespan disabled — dependencies are injected manually via set_dependencies.
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from app import scheduler as sched_module
from app.main import app
from app import routes as routes_module
from app.models import ScoredMarket
from app.scheduler import _set_state


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime(2026, 7, 6, 12, 0, 0, tzinfo=timezone.utc)


def _settings_obj():
    from app.config import Settings

    return Settings(
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
        kalshi_connector_url="http://mock-kc",
        kalshi_market_limit=100,
        postgres_url="",
        http_timeout=5.0,
        supported_categories="weather,sports",
    )


def _scored(ticker: str, tier: int, score: float = 50.0) -> ScoredMarket:
    return ScoredMarket(
        market_id=ticker,
        ticker=ticker,
        title=ticker,
        priority_score=score,
        assigned_tier=tier,
        scoring_timestamp=_now(),
        metadata={},
    )


@pytest.fixture()
def tc():
    """
    TestClient with lifespan suppressed.
    Injects mock dependencies and preset scheduler state.
    """
    mock_http = MagicMock(spec=httpx.AsyncClient)
    settings = _settings_obj()

    with patch("app.main.init_pool", new_callable=AsyncMock, return_value=None), \
         patch("app.main.scheduler_loop", new_callable=AsyncMock):
        with TestClient(app) as client:
            routes_module.set_dependencies(None, mock_http, settings)
            yield client, mock_http, settings

    # reset
    routes_module.set_dependencies(None, None, None)
    _set_state(None, [])


# ---------------------------------------------------------------------------
# GET /health — starting state
# ---------------------------------------------------------------------------


def test_health_starting_when_not_initialized():
    with patch("app.main.init_pool", new_callable=AsyncMock, return_value=None), \
         patch("app.main.scheduler_loop", new_callable=AsyncMock):
        with TestClient(app) as client:
            routes_module._http = None
            routes_module._settings = None
            r = client.get("/health")

    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "starting"
    assert data["kalshi_connector"] is False
    assert data["postgres"] is False
    assert data["markets_scored"] == 0


def test_health_ok_when_kalshi_reachable(tc):
    client, mock_http, settings = tc

    with patch("app.health.postgres_reachable", new_callable=AsyncMock, return_value=True), \
         patch("app.routes.KalshiConnectorClient") as MockKC:
        instance = MockKC.return_value
        instance.is_reachable = AsyncMock(return_value=True)
        r = client.get("/health")

    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert data["kalshi_connector"] is True


def test_health_degraded_when_kalshi_unreachable(tc):
    client, mock_http, settings = tc

    with patch("app.health.postgres_reachable", new_callable=AsyncMock, return_value=True), \
         patch("app.routes.KalshiConnectorClient") as MockKC:
        instance = MockKC.return_value
        instance.is_reachable = AsyncMock(return_value=False)
        r = client.get("/health")

    assert r.status_code == 200
    assert r.json()["status"] == "degraded"
    assert r.json()["kalshi_connector"] is False


def test_health_includes_markets_scored(tc):
    client, _, _ = tc
    _set_state(_now(), [_scored("T1", 2), _scored("T2", 3)])

    with patch("app.health.postgres_reachable", new_callable=AsyncMock, return_value=True), \
         patch("app.routes.KalshiConnectorClient") as MockKC:
        instance = MockKC.return_value
        instance.is_reachable = AsyncMock(return_value=True)
        r = client.get("/health")

    data = r.json()
    assert data["markets_scored"] == 2
    assert data["tier3_candidates"] == 1


def test_health_dry_run_safe_is_true(tc):
    client, _, _ = tc

    with patch("app.health.postgres_reachable", new_callable=AsyncMock, return_value=False), \
         patch("app.routes.KalshiConnectorClient") as MockKC:
        instance = MockKC.return_value
        instance.is_reachable = AsyncMock(return_value=True)
        r = client.get("/health")

    assert r.json()["dry_run_safe"] is True


# ---------------------------------------------------------------------------
# GET /opportunities
# ---------------------------------------------------------------------------


def test_opportunities_empty_when_no_scan(tc):
    client, _, _ = tc
    r = client.get("/opportunities")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 0
    assert data["markets"] == []


def test_opportunities_returns_all_markets(tc):
    client, _, _ = tc
    markets = [_scored(f"T{i}", i % 4) for i in range(8)]
    _set_state(_now(), markets)

    r = client.get("/opportunities")
    assert r.status_code == 200
    assert r.json()["total"] == 8


def test_opportunities_filter_by_tier(tc):
    client, _, _ = tc
    _set_state(
        _now(),
        [_scored("A", 2, 80), _scored("B", 3, 90), _scored("C", 1, 30)],
    )

    r = client.get("/opportunities?tier=3")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 1
    assert data["markets"][0]["ticker"] == "B"


def test_opportunities_limit(tc):
    client, _, _ = tc
    _set_state(_now(), [_scored(f"T{i}", 2) for i in range(20)])

    r = client.get("/opportunities?limit=5")
    assert r.status_code == 200
    assert r.json()["total"] == 5
    assert len(r.json()["markets"]) == 5


def test_opportunities_tier_and_limit_combined(tc):
    client, _, _ = tc
    _set_state(
        _now(),
        [_scored(f"T{i}", 2) for i in range(10)] + [_scored(f"X{i}", 3) for i in range(5)],
    )

    r = client.get("/opportunities?tier=2&limit=3")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 3
    assert all(m["assigned_tier"] == 2 for m in data["markets"])


def test_opportunities_tier_bounds_validated(tc):
    client, _, _ = tc
    r = client.get("/opportunities?tier=4")
    assert r.status_code == 422


def test_opportunities_limit_bounds_validated(tc):
    client, _, _ = tc
    r = client.get("/opportunities?limit=0")
    assert r.status_code == 422


def test_opportunities_tier_counts_in_response(tc):
    client, _, _ = tc
    _set_state(
        _now(),
        [_scored("A", 0), _scored("B", 1), _scored("C", 2), _scored("D", 3)],
    )

    r = client.get("/opportunities")
    tier_counts = r.json()["tier_counts"]
    assert tier_counts["0"] == 1
    assert tier_counts["1"] == 1
    assert tier_counts["2"] == 1
    assert tier_counts["3"] == 1


# ---------------------------------------------------------------------------
# GET /opportunities/top
# ---------------------------------------------------------------------------


def test_top_returns_only_tier3(tc):
    client, _, _ = tc
    _set_state(
        _now(),
        [_scored("A", 2, 70), _scored("B", 3, 90), _scored("C", 3, 85), _scored("D", 1, 20)],
    )

    r = client.get("/opportunities/top")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 2
    assert all(m["assigned_tier"] == 3 for m in data["markets"])


def test_top_respects_limit(tc):
    client, _, _ = tc
    _set_state(_now(), [_scored(f"T{i}", 3, float(100 - i)) for i in range(10)])

    r = client.get("/opportunities/top?limit=3")
    assert r.status_code == 200
    assert r.json()["total"] == 3


def test_top_empty_when_no_tier3(tc):
    client, _, _ = tc
    _set_state(_now(), [_scored("T1", 2), _scored("T2", 1)])

    r = client.get("/opportunities/top")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 0
    assert data["markets"] == []


# ---------------------------------------------------------------------------
# POST /refresh
# ---------------------------------------------------------------------------


def test_refresh_503_when_not_initialized():
    with patch("app.main.init_pool", new_callable=AsyncMock, return_value=None), \
         patch("app.main.scheduler_loop", new_callable=AsyncMock):
        with TestClient(app) as client:
            routes_module._http = None
            routes_module._settings = None
            r = client.post("/refresh")

    assert r.status_code == 503


def test_refresh_triggers_scan(tc):
    client, mock_http, settings = tc

    raw = [
        {
            "ticker": "SCAN-001",
            "title": "Scan Market",
            "status": "active",
            "yes_bid": 45,
            "yes_ask": 55,
            "no_bid": 45,
            "no_ask": 55,
            "volume": 1000,
            "open_interest": 500,
            "close_time": "2026-07-11T12:00:00+00:00",
            "result": None,
        }
    ]

    with patch("app.scheduler.KalshiConnectorClient") as MockKC:
        instance = MockKC.return_value
        instance.get_markets = AsyncMock(return_value=raw)
        r = client.post("/refresh")

    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert data["markets_scored"] == 1
    assert data["duration_ms"] >= 0
    assert "tier_counts" in data


def test_refresh_updates_in_memory_state(tc):
    client, mock_http, settings = tc

    raw = [
        {
            "ticker": "FRESH-001",
            "title": "Fresh Market",
            "status": "active",
            "yes_bid": 45,
            "yes_ask": 55,
            "no_bid": 45,
            "no_ask": 55,
            "volume": 2000,
            "open_interest": 800,
            "close_time": "2026-07-13T12:00:00+00:00",
            "result": None,
        }
    ]

    with patch("app.scheduler.KalshiConnectorClient") as MockKC:
        instance = MockKC.return_value
        instance.get_markets = AsyncMock(return_value=raw)
        client.post("/refresh")

    from app.scheduler import get_state
    _, markets = get_state()
    assert len(markets) == 1
    assert markets[0].ticker == "FRESH-001"


def test_refresh_empty_kalshi_returns_zero(tc):
    client, mock_http, settings = tc

    with patch("app.scheduler.KalshiConnectorClient") as MockKC:
        instance = MockKC.return_value
        instance.get_markets = AsyncMock(return_value=[])
        r = client.post("/refresh")

    assert r.status_code == 200
    assert r.json()["markets_scored"] == 0
