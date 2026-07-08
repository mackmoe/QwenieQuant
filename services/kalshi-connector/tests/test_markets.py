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
    assert ob.yes[0] == OrderBookLevel(price=55, count=100)
    assert ob.yes[1] == OrderBookLevel(price=54, count=200)


def test_normalize_orderbook_no_levels():
    raw = {"orderbook": {"yes": [], "no": [[43, 150], [42, 300]]}}
    ob = _normalize_orderbook("T", raw)
    assert len(ob.no) == 2
    assert ob.no[0] == OrderBookLevel(price=43, count=150)


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


# --- Current API format: dollar-string fields (api.elections.kalshi.com) ---


def _raw_market_dollars() -> dict:
    return {
        "ticker": "KXMLB-26-MILWIN",
        "event_ticker": "KXMLB-26JUL08MIL",
        "title": "Milwaukee wins",
        "status": "open",
        "yes_bid_dollars": "0.6100",
        "yes_ask_dollars": "0.6400",
        "no_bid_dollars": "0.3600",
        "no_ask_dollars": "0.3900",
        "volume_fp": "11627.90",
        "open_interest_fp": "5667.00",
        "close_time": "2026-07-08T23:00:00Z",
        "result": "",
    }


def test_normalize_market_dollar_fields_to_cents():
    m = _normalize_market(_raw_market_dollars())
    assert m.yes_bid == 61
    assert m.yes_ask == 64
    assert m.no_bid == 36
    assert m.no_ask == 39


def test_normalize_market_fp_counts_to_int():
    m = _normalize_market(_raw_market_dollars())
    assert m.volume == 11627
    assert m.open_interest == 5667


def test_normalize_market_captures_event_ticker():
    m = _normalize_market(_raw_market_dollars())
    assert m.event_ticker == "KXMLB-26JUL08MIL"


def test_normalize_market_subcent_price_rounds():
    raw = _raw_market_dollars()
    raw["yes_bid_dollars"] = "0.0020"  # 0.2¢ — fractional trading
    m = _normalize_market(raw)
    assert m.yes_bid == 0


def test_normalize_market_legacy_cent_fields_take_precedence():
    raw = _raw_market_dollars()
    raw["yes_bid"] = 55
    m = _normalize_market(raw)
    assert m.yes_bid == 55


def test_normalize_market_missing_dollar_fields_gives_none():
    raw = {"ticker": "T", "title": "x", "status": "open"}
    m = _normalize_market(raw)
    assert m.yes_bid is None
    assert m.yes_ask is None


def test_normalize_orderbook_fp_format():
    raw = {"orderbook_fp": {
        "yes_dollars": [["0.6100", "136.00"], ["0.6000", "5667.00"]],
        "no_dollars": [["0.3600", "42.00"]],
    }}
    ob = _normalize_orderbook("T", raw)
    assert ob.yes[0] == OrderBookLevel(price=61, count=136)
    assert ob.yes[1] == OrderBookLevel(price=60, count=5667)
    assert ob.no[0] == OrderBookLevel(price=36, count=42)


def test_normalize_orderbook_fp_empty_sides():
    raw = {"orderbook_fp": {"yes_dollars": [], "no_dollars": []}}
    ob = _normalize_orderbook("T", raw)
    assert ob.yes == []
    assert ob.no == []


def test_normalize_market_captures_mve_collection_ticker():
    raw = _raw_market_dollars()
    raw["mve_collection_ticker"] = "KXMVECROSSCATEGORY"
    m = _normalize_market(raw)
    assert m.mve_collection_ticker == "KXMVECROSSCATEGORY"


def test_normalize_market_empty_mve_ticker_is_none():
    raw = _raw_market_dollars()
    raw["mve_collection_ticker"] = ""
    m = _normalize_market(raw)
    assert m.mve_collection_ticker is None


async def test_get_markets_follows_cursor_pagination():
    from unittest.mock import AsyncMock, MagicMock
    client = MagicMock()
    client.get = AsyncMock(side_effect=[
        {"markets": [_raw_market_dollars() for _ in range(2)], "cursor": "next"},
        {"markets": [_raw_market_dollars()], "cursor": None},
    ])
    result = await get_markets(client, limit=3)
    assert len(result) == 3
    assert client.get.call_count == 2
    assert client.get.call_args_list[1][1]["params"]["cursor"] == "next"


async def test_get_markets_stops_at_limit():
    from unittest.mock import AsyncMock, MagicMock
    client = MagicMock()
    client.get = AsyncMock(return_value={"markets": [_raw_market_dollars()], "cursor": "more"})
    result = await get_markets(client, limit=2)
    assert len(result) == 2
    assert client.get.call_count == 2
