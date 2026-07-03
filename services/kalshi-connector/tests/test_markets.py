from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.markets import (
    Market,
    OrderBook,
    OrderBookLevel,
    _normalize_market,
    _normalize_orderbook,
    get_market,
    get_markets,
    get_orderbook,
)


def _raw_market(**overrides) -> dict:
    base = {
        "ticker": "AAPL-24-GT150",
        "title": "Will AAPL close above $150?",
        "status": "active",
        "yes_bid": 55,
        "yes_ask": 57,
        "no_bid": 43,
        "no_ask": 45,
        "volume": 1000,
        "open_interest": 200,
        "close_time": "2024-12-31T23:59:00Z",
        "result": "",
    }
    base.update(overrides)
    return base


# ── _normalize_market ──────────────────────────────────────────────────────


def test_normalize_market_ticker():
    m = _normalize_market(_raw_market())
    assert m.ticker == "AAPL-24-GT150"


def test_normalize_market_title():
    m = _normalize_market(_raw_market())
    assert m.title == "Will AAPL close above $150?"


def test_normalize_market_status():
    m = _normalize_market(_raw_market(status="closed"))
    assert m.status == "closed"


def test_normalize_market_prices():
    m = _normalize_market(_raw_market())
    assert m.yes_bid == 55
    assert m.yes_ask == 57
    assert m.no_bid == 43
    assert m.no_ask == 45


def test_normalize_market_volume_and_oi():
    m = _normalize_market(_raw_market())
    assert m.volume == 1000
    assert m.open_interest == 200


def test_normalize_market_close_time_parsed():
    m = _normalize_market(_raw_market())
    assert m.close_time is not None
    assert m.close_time.year == 2024


def test_normalize_market_empty_result_becomes_none():
    m = _normalize_market(_raw_market(result=""))
    assert m.result is None


def test_normalize_market_result_set():
    m = _normalize_market(_raw_market(result="yes"))
    assert m.result == "yes"


def test_normalize_market_missing_optional_fields():
    m = _normalize_market({"ticker": "X", "title": "Y", "status": "active"})
    assert m.yes_bid is None
    assert m.close_time is None
    assert m.volume == 0


def test_normalize_market_invalid_close_time_becomes_none():
    m = _normalize_market(_raw_market(close_time="not-a-date"))
    assert m.close_time is None


# ── _normalize_orderbook ───────────────────────────────────────────────────


def test_normalize_orderbook_ticker():
    raw = {"orderbook": {"yes": [[55, 100]], "no": [[43, 150]]}}
    ob = _normalize_orderbook("AAPL-24-GT150", raw)
    assert ob.ticker == "AAPL-24-GT150"


def test_normalize_orderbook_yes_levels():
    raw = {"orderbook": {"yes": [[55, 100], [54, 200]], "no": []}}
    ob = _normalize_orderbook("T", raw)
    assert len(ob.yes) == 2
    assert ob.yes[0] == OrderBookLevel(price=55, quantity=100)
    assert ob.yes[1] == OrderBookLevel(price=54, quantity=200)


def test_normalize_orderbook_no_levels():
    raw = {"orderbook": {"yes": [], "no": [[43, 150], [42, 300]]}}
    ob = _normalize_orderbook("T", raw)
    assert len(ob.no) == 2
    assert ob.no[0] == OrderBookLevel(price=43, quantity=150)


def test_normalize_orderbook_empty_book():
    raw = {"orderbook": {"yes": [], "no": []}}
    ob = _normalize_orderbook("T", raw)
    assert ob.yes == []
    assert ob.no == []


def test_normalize_orderbook_missing_wrapper():
    raw = {"yes": [[55, 100]], "no": []}
    ob = _normalize_orderbook("T", raw)
    assert len(ob.yes) == 1


# ── async functions ────────────────────────────────────────────────────────


async def test_get_markets_calls_correct_path():
    client = MagicMock()
    client.get = AsyncMock(return_value={"markets": [_raw_market()]})
    result = await get_markets(client)
    client.get.assert_called_once()
    call_path = client.get.call_args[0][0]
    assert call_path == "/markets"
    assert isinstance(result[0], Market)


async def test_get_markets_passes_limit_and_status():
    client = MagicMock()
    client.get = AsyncMock(return_value={"markets": []})
    await get_markets(client, limit=25, status="closed")
    params = client.get.call_args[1]["params"]
    assert params["limit"] == 25
    assert params["status"] == "closed"


async def test_get_markets_passes_series_ticker():
    client = MagicMock()
    client.get = AsyncMock(return_value={"markets": []})
    await get_markets(client, series_ticker="AAPL")
    params = client.get.call_args[1]["params"]
    assert params["series_ticker"] == "AAPL"


async def test_get_markets_omits_series_ticker_when_none():
    client = MagicMock()
    client.get = AsyncMock(return_value={"markets": []})
    await get_markets(client, series_ticker=None)
    params = client.get.call_args[1]["params"]
    assert "series_ticker" not in params


async def test_get_market_calls_ticker_path():
    client = MagicMock()
    client.get = AsyncMock(return_value={"market": _raw_market()})
    result = await get_market(client, "AAPL-24-GT150")
    client.get.assert_called_once_with("/markets/AAPL-24-GT150")
    assert isinstance(result, Market)


async def test_get_orderbook_calls_ticker_path():
    raw = {"orderbook": {"yes": [[55, 100]], "no": []}}
    client = MagicMock()
    client.get = AsyncMock(return_value=raw)
    result = await get_orderbook(client, "AAPL-24-GT150")
    client.get.assert_called_once_with("/markets/AAPL-24-GT150/orderbook")
    assert isinstance(result, OrderBook)
