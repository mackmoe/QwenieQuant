"""
Tests for queue_publisher: _build_payload, publish_opportunities.
No live services — Prediction Queue is mocked throughout.
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.config import Settings
from app.models import ScoredMarket
from app.queue_publisher import _build_payload, publish_opportunities


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _settings(**overrides) -> Settings:
    defaults = dict(
        discovery_interval_seconds=300,
        max_tier2_markets=100,
        max_tier3_markets=30,
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
        prediction_queue_url="http://mock-queue:8006",
        publish_to_queue=True,
        queue_publish_batch_size=10,
    )
    defaults.update(overrides)
    return Settings(**defaults)


def _now() -> datetime:
    return datetime(2026, 7, 6, 12, 0, 0, tzinfo=timezone.utc)


def _make_scored(ticker: str, tier: int, score: float = 50.0) -> ScoredMarket:
    return ScoredMarket(
        market_id=ticker,
        ticker=ticker,
        title=f"Title for {ticker}",
        priority_score=score,
        assigned_tier=tier,
        scoring_timestamp=_now(),
        metadata={"days_remaining": 3.0, "time_score": 1.0},
    )


def _mock_http(status: int = 200, json_data: dict | None = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = json_data or {"added": 5, "updated": 2, "queue_size": 7}
    if status >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            f"HTTP {status}", request=MagicMock(), response=resp
        )
    else:
        resp.raise_for_status.return_value = None
    http = MagicMock()
    http.post = AsyncMock(return_value=resp)
    return http


# ---------------------------------------------------------------------------
# _build_payload
# ---------------------------------------------------------------------------


def test_build_payload_structure():
    markets = [_make_scored("T1", 3, 80.0), _make_scored("T2", 3, 70.0)]
    payload = _build_payload(markets)
    assert "opportunities" in payload
    assert len(payload["opportunities"]) == 2


def test_build_payload_required_fields():
    market = _make_scored("KXBTC", 3, 90.0)
    payload = _build_payload([market])
    opp = payload["opportunities"][0]
    assert opp["market_id"] == "KXBTC"
    assert opp["ticker"] == "KXBTC"
    assert opp["priority_score"] == 90.0


def test_build_payload_metadata_includes_title_and_tier():
    market = _make_scored("T1", 3)
    payload = _build_payload([market])
    meta = payload["opportunities"][0]["metadata"]
    assert meta["title"] == "Title for T1"
    assert meta["assigned_tier"] == 3


def test_build_payload_metadata_includes_scorer_factors():
    market = _make_scored("T1", 3)
    payload = _build_payload([market])
    meta = payload["opportunities"][0]["metadata"]
    assert "days_remaining" in meta
    assert "time_score" in meta


def test_build_payload_empty_list():
    assert _build_payload([]) == {"opportunities": []}


# ---------------------------------------------------------------------------
# publish_opportunities — disabled
# ---------------------------------------------------------------------------


async def test_publish_disabled_returns_zero_without_http_call():
    http = _mock_http()
    s = _settings(publish_to_queue=False)
    markets = [_make_scored("T1", 3)]
    result = await publish_opportunities(http, s, markets)
    assert result == 0
    http.post.assert_not_called()


# ---------------------------------------------------------------------------
# publish_opportunities — empty batch
# ---------------------------------------------------------------------------


async def test_publish_empty_markets_returns_zero():
    http = _mock_http()
    result = await publish_opportunities(http, _settings(), [])
    assert result == 0
    http.post.assert_not_called()


# ---------------------------------------------------------------------------
# publish_opportunities — successful publish
# ---------------------------------------------------------------------------


async def test_publish_returns_batch_count_on_success():
    http = _mock_http(json_data={"added": 3, "updated": 0, "queue_size": 3})
    markets = [_make_scored(f"T{i}", 3) for i in range(5)]
    result = await publish_opportunities(http, _settings(), markets)
    assert result == 5


async def test_publish_posts_to_correct_url():
    http = _mock_http()
    await publish_opportunities(http, _settings(), [_make_scored("T1", 3)])
    call_args = http.post.call_args
    assert call_args[0][0] == "http://mock-queue:8006/queue/add"


async def test_publish_posts_json_payload():
    http = _mock_http()
    markets = [_make_scored("T1", 3, 85.0), _make_scored("T2", 3, 75.0)]
    await publish_opportunities(http, _settings(), markets)
    payload = http.post.call_args[1]["json"]
    assert "opportunities" in payload
    assert len(payload["opportunities"]) == 2


# ---------------------------------------------------------------------------
# publish_opportunities — batch size cap
# ---------------------------------------------------------------------------


async def test_publish_respects_batch_size():
    http = _mock_http()
    markets = [_make_scored(f"T{i}", 3) for i in range(20)]
    s = _settings(queue_publish_batch_size=5)
    result = await publish_opportunities(http, s, markets)
    assert result == 5
    payload = http.post.call_args[1]["json"]
    assert len(payload["opportunities"]) == 5


async def test_publish_batch_size_larger_than_input():
    http = _mock_http()
    markets = [_make_scored(f"T{i}", 3) for i in range(3)]
    s = _settings(queue_publish_batch_size=10)
    result = await publish_opportunities(http, s, markets)
    assert result == 3


# ---------------------------------------------------------------------------
# publish_opportunities — failure handling
# ---------------------------------------------------------------------------


async def test_publish_http_error_returns_zero():
    http = _mock_http(status=503)
    result = await publish_opportunities(http, _settings(), [_make_scored("T1", 3)])
    assert result == 0


async def test_publish_connection_error_returns_zero():
    http = MagicMock()
    http.post = AsyncMock(side_effect=Exception("Connection refused"))
    result = await publish_opportunities(http, _settings(), [_make_scored("T1", 3)])
    assert result == 0


async def test_publish_connection_error_does_not_raise():
    http = MagicMock()
    http.post = AsyncMock(side_effect=Exception("Timeout"))
    # Must not raise — caller should never see an exception
    await publish_opportunities(http, _settings(), [_make_scored("T1", 3)])


async def test_publish_timeout_returns_zero():
    http = MagicMock()
    http.post = AsyncMock(side_effect=httpx.TimeoutException("Timeout"))
    result = await publish_opportunities(http, _settings(), [_make_scored("T1", 3)])
    assert result == 0
