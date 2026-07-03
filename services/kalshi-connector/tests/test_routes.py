from unittest.mock import AsyncMock, MagicMock, patch

import app.routes as routes_module
import pytest
from fastapi.testclient import TestClient

from app.client import (
    AuthenticationError,
    InvalidOrderError,
    MarketNotFoundError,
    ServiceUnavailableError,
)
from app.main import app
from app.routes import set_client


def _mock_client(configured: bool = True, reachable: bool = True) -> MagicMock:
    client = MagicMock()
    client.is_configured.return_value = configured
    client.probe_reachable = AsyncMock(return_value=reachable)
    return client


def _market_dict() -> dict:
    return {
        "ticker": "T",
        "title": "Test",
        "status": "active",
        "yes_bid": 50,
        "yes_ask": 52,
        "no_bid": 48,
        "no_ask": 50,
        "volume": 100,
        "open_interest": 10,
        "close_time": None,
        "result": None,
    }


def _order_dict() -> dict:
    return {
        "order_id": "ord-1",
        "ticker": "T",
        "side": "yes",
        "action": "buy",
        "quantity": 5,
        "price": 55,
        "order_type": "limit",
        "status": "resting",
        "filled_count": 0,
        "remaining_count": 5,
        "created_time": None,
    }


@pytest.fixture
def tc():
    """TestClient with lifespan, then mock client injected after startup."""
    mock = _mock_client()
    with TestClient(app) as client:
        set_client(mock, "demo")
        yield client, mock
    set_client(None, "demo")


# ── /health ────────────────────────────────────────────────────────────────


def test_health_ok(tc):
    client, mock = tc
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["environment"] == "demo"
    assert body["credentials_configured"] is True
    assert body["kalshi_reachable"] is True


def test_health_degraded_when_not_configured(tc):
    client, mock = tc
    mock.is_configured.return_value = False
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "degraded"
    assert r.json()["credentials_configured"] is False


def test_health_degraded_when_unreachable(tc):
    client, mock = tc
    mock.probe_reachable = AsyncMock(return_value=False)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "degraded"
    assert r.json()["kalshi_reachable"] is False


def test_health_starting_when_no_client(tc):
    client, _ = tc
    routes_module._client = None
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "starting"


def test_health_includes_version(tc):
    client, _ = tc
    r = client.get("/health")
    assert "version" in r.json()


# ── /markets ────────────────────────────────────────────────────────────────


def test_get_markets_returns_200(tc):
    client, _ = tc
    with patch("app.routes.get_markets", new_callable=AsyncMock) as mock_fn:
        from app.markets import Market
        mock_fn.return_value = [Market(**_market_dict())]
        r = client.get("/markets")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_get_markets_passes_query_params(tc):
    client, _ = tc
    with patch("app.routes.get_markets", new_callable=AsyncMock) as mock_fn:
        mock_fn.return_value = []
        client.get("/markets?limit=25&status=closed")
    call_kwargs = mock_fn.call_args[1]
    assert call_kwargs["limit"] == 25
    assert call_kwargs["status"] == "closed"


def test_get_markets_kalshi_error_returns_503(tc):
    client, _ = tc
    with patch("app.routes.get_markets", new_callable=AsyncMock) as mock_fn:
        mock_fn.side_effect = ServiceUnavailableError()
        r = client.get("/markets")
    assert r.status_code == 503


# ── /market/{ticker} ───────────────────────────────────────────────────────


def test_get_market_returns_200(tc):
    client, _ = tc
    with patch("app.routes.get_market", new_callable=AsyncMock) as mock_fn:
        from app.markets import Market
        mock_fn.return_value = Market(**_market_dict())
        r = client.get("/market/T")
    assert r.status_code == 200
    assert r.json()["ticker"] == "T"


def test_get_market_not_found_returns_404(tc):
    client, _ = tc
    with patch("app.routes.get_market", new_callable=AsyncMock) as mock_fn:
        mock_fn.side_effect = MarketNotFoundError("T")
        r = client.get("/market/T")
    assert r.status_code == 404


# ── /orderbook/{ticker} ────────────────────────────────────────────────────


def test_get_orderbook_returns_200(tc):
    client, _ = tc
    with patch("app.routes.get_orderbook", new_callable=AsyncMock) as mock_fn:
        from app.markets import OrderBook
        mock_fn.return_value = OrderBook(ticker="T", yes=[], no=[])
        r = client.get("/orderbook/T")
    assert r.status_code == 200
    assert r.json()["ticker"] == "T"


# ── /positions ─────────────────────────────────────────────────────────────


def test_get_positions_returns_200(tc):
    client, _ = tc
    with patch("app.routes.get_positions", new_callable=AsyncMock) as mock_fn:
        mock_fn.return_value = []
        r = client.get("/positions")
    assert r.status_code == 200
    assert r.json() == []


# ── /account ───────────────────────────────────────────────────────────────


def test_get_account_returns_200(tc):
    client, _ = tc
    with patch("app.routes.get_account", new_callable=AsyncMock) as mock_fn:
        from app.positions import Account
        mock_fn.return_value = Account(balance=100000, portfolio_value=0)
        r = client.get("/account")
    assert r.status_code == 200
    assert r.json()["balance"] == 100000


def test_get_account_auth_error_returns_401(tc):
    client, _ = tc
    with patch("app.routes.get_account", new_callable=AsyncMock) as mock_fn:
        mock_fn.side_effect = AuthenticationError()
        r = client.get("/account")
    assert r.status_code == 401


# ── POST /order ────────────────────────────────────────────────────────────


def test_post_order_returns_200(tc):
    client, _ = tc
    with patch("app.routes.place_order", new_callable=AsyncMock) as mock_fn:
        from app.orders import Order
        mock_fn.return_value = Order(**_order_dict())
        r = client.post("/order", json={
            "ticker": "T",
            "side": "yes",
            "action": "buy",
            "quantity": 5,
            "price": 55,
        })
    assert r.status_code == 200
    assert r.json()["order_id"] == "ord-1"


def test_post_order_invalid_returns_400(tc):
    client, _ = tc
    with patch("app.routes.place_order", new_callable=AsyncMock) as mock_fn:
        mock_fn.side_effect = InvalidOrderError("Insufficient funds")
        r = client.post("/order", json={
            "ticker": "T",
            "side": "yes",
            "action": "buy",
            "quantity": 5,
            "price": 55,
        })
    assert r.status_code == 400


def test_post_order_bad_request_body_returns_422(tc):
    client, _ = tc
    r = client.post("/order", json={"ticker": "T"})  # missing required fields
    assert r.status_code == 422


# ── POST /cancel ───────────────────────────────────────────────────────────


def test_post_cancel_returns_200(tc):
    client, _ = tc
    with patch("app.routes.cancel_order", new_callable=AsyncMock) as mock_fn:
        from app.orders import Order
        mock_fn.return_value = Order(**{**_order_dict(), "status": "canceled"})
        r = client.post("/cancel", json={"order_id": "ord-1"})
    assert r.status_code == 200
    assert r.json()["status"] == "canceled"


def test_post_cancel_passes_order_id(tc):
    client, _ = tc
    with patch("app.routes.cancel_order", new_callable=AsyncMock) as mock_fn:
        from app.orders import Order
        mock_fn.return_value = Order(**_order_dict())
        client.post("/cancel", json={"order_id": "ord-xyz"})
    mock_fn.assert_called_once()
    assert mock_fn.call_args[0][1] == "ord-xyz"
