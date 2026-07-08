"""Tests for the /markets command: handler, formatter, and client."""

from unittest.mock import AsyncMock, MagicMock

from app.clients import OpportunityClient
from app.commands import handle_markets
from app.formatter import format_markets, _fmt_expiry

_ALLOWED_IDS = [111111111111111111]

_MARKET_A = {
    "market_id": "KXBTC-24DEC25-T120000",
    "ticker": "KXBTC-24DEC25-T120000",
    "title": "Will BTC close above $120,000 today?",
    "priority_score": 94.2,
    "assigned_tier": 3,
    "scoring_timestamp": "2026-07-06T12:00:00Z",
    "metadata": {"days_remaining": 0.18, "time_score": 0.5},
}

_MARKET_B = {
    "market_id": "KXWEATHER-DALLAS-100F",
    "ticker": "KXWEATHER-DALLAS-100F",
    "title": "Will Dallas reach 100°F tomorrow?",
    "priority_score": 91.7,
    "assigned_tier": 3,
    "scoring_timestamp": "2026-07-06T12:00:00Z",
    "metadata": {"days_remaining": 1.71, "time_score": 1.0},
}

_OPP_RESPONSE = {
    "markets": [_MARKET_A, _MARKET_B],
    "total": 843,
    "tier_counts": {"0": 0, "1": 900, "2": 70, "3": 30},
    "scored_at": "2026-07-06T12:00:00Z",
    "version": "0.1.0",
}

_EMPTY_RESPONSE = {
    "markets": [],
    "total": 0,
    "tier_counts": {"0": 0, "1": 0, "2": 0, "3": 0},
    "scored_at": "2026-07-06T12:00:00Z",
    "version": "0.1.0",
}


def _opp_client(response=None):
    c = MagicMock()
    c.get_opportunities = AsyncMock(return_value=response or _OPP_RESPONSE)
    return c


# ---------------------------------------------------------------------------
# _fmt_expiry
# ---------------------------------------------------------------------------


def test_fmt_expiry_none_returns_unknown():
    assert _fmt_expiry(None) == "Unknown"


def test_fmt_expiry_negative_returns_expired():
    assert _fmt_expiry(-0.5) == "Expired"


def test_fmt_expiry_less_than_one_day():
    assert _fmt_expiry(0.5) == "12h"


def test_fmt_expiry_one_and_a_half_days():
    assert _fmt_expiry(1.5) == "1d 12h"


def test_fmt_expiry_whole_days_no_hours():
    assert _fmt_expiry(3.0) == "3d"


def test_fmt_expiry_zero_hours():
    assert _fmt_expiry(0.04) == "< 1h"


# ---------------------------------------------------------------------------
# format_markets
# ---------------------------------------------------------------------------


def test_format_markets_shows_heading():
    result = format_markets(_OPP_RESPONSE)
    assert "Kalshi Market Opportunities" in result


def test_format_markets_shows_market_titles():
    result = format_markets(_OPP_RESPONSE)
    assert "BTC" in result
    assert "Dallas" in result


def test_format_markets_shows_priority_scores():
    result = format_markets(_OPP_RESPONSE)
    assert "94.2" in result
    assert "91.7" in result


def test_format_markets_shows_tier():
    result = format_markets(_OPP_RESPONSE)
    assert "T:3" in result


def test_format_markets_shows_expiry():
    result = format_markets(_OPP_RESPONSE)
    assert "h" in result  # expiry always contains a time unit


def test_format_markets_shows_total_count():
    result = format_markets(_OPP_RESPONSE)
    assert "843" in result


def test_format_markets_empty_returns_no_opportunities():
    result = format_markets(_EMPTY_RESPONSE)
    assert "No opportunities are currently available." in result


def test_format_markets_error_returns_unavailable():
    result = format_markets({"error": "Connection refused"})
    assert "❌" in result
    assert "unavailable" in result.lower()


def test_format_markets_truncates_long_title():
    long_market = {**_MARKET_A, "title": "X" * 200}
    result = format_markets({"markets": [long_market], "total": 1})
    assert "…" in result


def test_format_markets_category_filter_all_passes_through():
    result = format_markets(_OPP_RESPONSE, category="all")
    assert "BTC" in result
    assert "Dallas" in result


def test_format_markets_category_filter_matches_title():
    result = format_markets(_OPP_RESPONSE, category="dallas")
    assert "Dallas" in result


def test_format_markets_category_filter_no_matches_returns_empty():
    result = format_markets(_OPP_RESPONSE, category="politics")
    assert "No opportunities" in result


# ---------------------------------------------------------------------------
# handle_markets — command handler
# ---------------------------------------------------------------------------


async def test_handle_markets_returns_string():
    result = await handle_markets(_ALLOWED_IDS[0], _opp_client())
    assert isinstance(result, str)


async def test_handle_markets_calls_get_opportunities():
    client = _opp_client()
    await handle_markets(_ALLOWED_IDS[0], client)
    client.get_opportunities.assert_called_once()


async def test_handle_markets_default_limit_is_ten():
    client = _opp_client()
    await handle_markets(_ALLOWED_IDS[0], client)
    _, kwargs = client.get_opportunities.call_args
    assert kwargs.get("limit", 10) == 10


async def test_handle_markets_passes_limit():
    client = _opp_client()
    await handle_markets(_ALLOWED_IDS[0], client, limit=5)
    client.get_opportunities.assert_called_once_with(limit=5)


async def test_handle_markets_empty_response():
    result = await handle_markets(_ALLOWED_IDS[0], _opp_client(_EMPTY_RESPONSE))
    assert "No opportunities" in result


async def test_handle_markets_service_unavailable():
    result = await handle_markets(
        _ALLOWED_IDS[0],
        _opp_client({"error": "Connection refused", "reachable": False}),
    )
    assert "❌" in result
    assert "unavailable" in result.lower()


async def test_handle_markets_with_category_finance():
    result = await handle_markets(
        _ALLOWED_IDS[0], _opp_client(), category="finance"
    )
    assert isinstance(result, str)


# ---------------------------------------------------------------------------
# OpportunityClient
# ---------------------------------------------------------------------------


def _mock_http(json_data: dict = None, status_code: int = 200):
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = json_data or {}
    response.raise_for_status.return_value = None
    http = MagicMock()
    http.get = AsyncMock(return_value=response)
    http.post = AsyncMock(return_value=response)
    return http


async def test_opportunity_client_health_ok():
    http = _mock_http({"status": "ok"})
    client = OpportunityClient("http://opportunity-engine:8005", http)
    result = await client.health()
    assert result["status"] == "ok"


async def test_opportunity_client_get_opportunities_success():
    http = _mock_http(_OPP_RESPONSE)
    client = OpportunityClient("http://opportunity-engine:8005", http)
    result = await client.get_opportunities(limit=10)
    assert "markets" in result
    assert result["total"] == 843


async def test_opportunity_client_get_opportunities_connection_error():
    http = MagicMock()
    http.get = AsyncMock(side_effect=Exception("Connection refused"))
    client = OpportunityClient("http://opportunity-engine:8005", http)
    result = await client.get_opportunities()
    assert "error" in result
