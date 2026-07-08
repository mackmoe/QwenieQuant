from unittest.mock import AsyncMock, MagicMock

import pytest

from app.orders import (
    CancelOrderRequest,
    Order,
    PlaceOrderRequest,
    _normalize_order,
    cancel_order,
    place_order,
)


def _raw_order(**overrides) -> dict:
    base = {
        "order_id": "ord-abc123",
        "ticker": "AAPL-24-GT150",
        "side": "yes",
        "action": "buy",
        "count": 10,
        "yes_price": 55,
        "type": "limit",
        "status": "resting",
        "filled_count": 0,
        "remaining_count": 10,
        "created_time": "2024-06-01T12:00:00Z",
    }
    base.update(overrides)
    return base


# ── PlaceOrderRequest validation ───────────────────────────────────────────


def test_place_order_request_valid():
    r = PlaceOrderRequest(ticker="T", side="yes", action="buy", count=5, price=55)
    assert r.side == "yes"
    assert r.action == "buy"


def test_place_order_request_invalid_side():
    with pytest.raises(Exception):
        PlaceOrderRequest(ticker="T", side="both", action="buy", count=5, price=55)


def test_place_order_request_invalid_action():
    with pytest.raises(Exception):
        PlaceOrderRequest(ticker="T", side="yes", action="hold", count=5, price=55)


def test_place_order_request_no_side_defaults():
    r = PlaceOrderRequest(ticker="T", side="no", action="sell", count=1, price=45)
    assert r.side == "no"
    assert r.order_type == "limit"


# ── _normalize_order ────────────────────────────────────────────────────────


def test_normalize_order_unwraps_order_key():
    raw = {"order": _raw_order()}
    o = _normalize_order(raw)
    assert o.order_id == "ord-abc123"


def test_normalize_order_flat_dict():
    o = _normalize_order(_raw_order())
    assert o.order_id == "ord-abc123"


def test_normalize_order_yes_side_uses_yes_price():
    o = _normalize_order(_raw_order(side="yes", yes_price=55))
    assert o.price == 55
    assert o.side == "yes"


def test_normalize_order_no_side_uses_no_price():
    raw = _raw_order(side="no", no_price=45)
    raw.pop("yes_price", None)
    o = _normalize_order(raw)
    assert o.price == 45
    assert o.side == "no"


def test_normalize_order_quantity_from_count():
    o = _normalize_order(_raw_order(count=7))
    assert o.count == 7


def test_normalize_order_status():
    o = _normalize_order(_raw_order(status="filled"))
    assert o.status == "filled"


def test_normalize_order_created_time_parsed():
    o = _normalize_order(_raw_order())
    assert o.created_time is not None
    assert o.created_time.year == 2024


def test_normalize_order_invalid_created_time():
    o = _normalize_order(_raw_order(created_time="not-a-date"))
    assert o.created_time is None


def test_normalize_order_filled_and_remaining():
    o = _normalize_order(_raw_order(filled_count=3, remaining_count=7))
    assert o.filled_count == 3
    assert o.remaining_count == 7


# ── place_order ─────────────────────────────────────────────────────────────


async def test_place_order_posts_to_correct_path():
    client = MagicMock()
    client.post = AsyncMock(return_value={"order": _raw_order()})
    request = PlaceOrderRequest(ticker="AAPL", side="yes", action="buy", count=10, price=55)
    result = await place_order(client, request)
    client.post.assert_called_once()
    call_path = client.post.call_args[0][0]
    assert call_path == "/portfolio/orders"
    assert isinstance(result, Order)


async def test_place_order_yes_uses_yes_price_key():
    client = MagicMock()
    client.post = AsyncMock(return_value={"order": _raw_order()})
    request = PlaceOrderRequest(ticker="T", side="yes", action="buy", count=5, price=60)
    await place_order(client, request)
    payload = client.post.call_args[1]["json"]
    assert "yes_price" in payload
    assert payload["yes_price"] == 60
    assert "no_price" not in payload


async def test_place_order_no_uses_no_price_key():
    client = MagicMock()
    client.post = AsyncMock(return_value={"order": _raw_order(side="no", no_price=45)})
    request = PlaceOrderRequest(ticker="T", side="no", action="buy", count=5, price=45)
    await place_order(client, request)
    payload = client.post.call_args[1]["json"]
    assert "no_price" in payload
    assert payload["no_price"] == 45


async def test_place_order_includes_all_required_fields():
    client = MagicMock()
    client.post = AsyncMock(return_value={"order": _raw_order()})
    request = PlaceOrderRequest(ticker="T", side="yes", action="sell", count=3, price=70)
    await place_order(client, request)
    payload = client.post.call_args[1]["json"]
    assert payload["ticker"] == "T"
    assert payload["action"] == "sell"
    assert payload["type"] == "limit"
    assert payload["side"] == "yes"
    assert payload["count"] == 3


# ── cancel_order ────────────────────────────────────────────────────────────


async def test_cancel_order_calls_delete_with_order_id():
    client = MagicMock()
    client.delete = AsyncMock(return_value={"order": _raw_order(status="canceled")})
    result = await cancel_order(client, "ord-abc123")
    client.delete.assert_called_once_with("/portfolio/orders/ord-abc123")
    assert result.status == "canceled"


async def test_cancel_order_returns_order_model():
    client = MagicMock()
    client.delete = AsyncMock(return_value={"order": _raw_order()})
    result = await cancel_order(client, "x")
    assert isinstance(result, Order)
