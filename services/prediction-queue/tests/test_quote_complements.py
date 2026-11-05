"""Regression tests for executable YES/NO quote discovery (no trades placed)."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.config import Settings
from app.workflow import _fetch_market_price


def _mock_http(market):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = market
    http = MagicMock()
    http.get = AsyncMock(return_value=resp)
    return http


@pytest.mark.asyncio
async def test_yes_ask_is_derived_from_no_bid():
    # A resting NO bid at 41c is a YES ask at 59c.
    quote = await _fetch_market_price(
        _mock_http({"yes_bid": 35, "no_bid": 41, "yes_ask": None, "no_ask": None}),
        Settings(), "TEST-MARKET"
    )
    assert quote["yes_ask_cents"] == 59
    assert quote["no_ask_cents"] == 65
    assert quote["mid"] == pytest.approx(0.47)


@pytest.mark.asyncio
async def test_explicit_yes_ask_takes_precedence_over_inferred_ask():
    quote = await _fetch_market_price(
        _mock_http({"yes_bid": 35, "no_bid": 41, "yes_ask": 61, "no_ask": None}),
        Settings(), "TEST-MARKET"
    )
    assert quote["yes_ask_cents"] == 61
    assert quote["no_ask_cents"] == 65


@pytest.mark.asyncio
async def test_no_bid_only_yields_yes_ask_and_no_fake_no_ask():
    quote = await _fetch_market_price(
        _mock_http({"no_bid": 25}), Settings(), "TEST-MARKET"
    )
    assert quote["yes_ask_cents"] == 75
    assert quote["no_ask_cents"] is None
    assert quote["mid"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("bid", [None, 0, 100, -1, 101, True, "42", 0.4])
async def test_invalid_bid_does_not_generate_an_executable_ask(bid):
    quote = await _fetch_market_price(
        _mock_http({"no_bid": bid}), Settings(), "TEST-MARKET"
    )
    assert quote is None


@pytest.mark.asyncio
async def test_last_trade_price_is_not_treated_as_executable():
    quote = await _fetch_market_price(
        _mock_http({"last_price": 55, "yes_ask": None, "no_ask": None}),
        Settings(), "TEST-MARKET"
    )
    assert quote is None


@pytest.mark.asyncio
async def test_yes_bid_only_generates_no_ask():
    quote = await _fetch_market_price(
        _mock_http({"yes_bid": 67}), Settings(), "TEST-MARKET"
    )
    assert quote["yes_ask_cents"] is None
    assert quote["no_ask_cents"] == 33
