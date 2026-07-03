import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.client import (
    AuthenticationError,
    InvalidOrderError,
    KalshiClient,
    KalshiError,
    MarketNotFoundError,
    RateLimitError,
    ServiceUnavailableError,
)


def _mock_response(status_code: int, json_data: dict | None = None, headers: dict | None = None):
    response = MagicMock(spec=httpx.Response)
    response.status_code = status_code
    response.json.return_value = json_data or {}
    response.headers = headers or {}
    return response


def _make_client(mock_http: MagicMock, max_retries: int = 0) -> KalshiClient:
    return KalshiClient(
        base_url="https://demo-api.kalshi.co/trade-api/v2",
        api_key="test-key",
        private_key_pem="test-pem",
        http=mock_http,
        max_retries=max_retries,
    )


def _patched_client(max_retries: int = 0):
    http = MagicMock()
    client = _make_client(http, max_retries=max_retries)
    return client, http


@pytest.fixture(autouse=True)
def patch_auth():
    with patch("app.client.build_auth_headers", return_value={"Authorization": "mock"}):
        yield


async def test_get_200_returns_json():
    http = MagicMock()
    http.request = AsyncMock(return_value=_mock_response(200, {"markets": []}))
    client = _make_client(http)
    result = await client.get("/markets")
    assert result == {"markets": []}


async def test_post_201_returns_json():
    http = MagicMock()
    http.request = AsyncMock(return_value=_mock_response(201, {"order": {"order_id": "x"}}))
    client = _make_client(http)
    result = await client.post("/portfolio/orders", json={"ticker": "X"})
    assert result == {"order": {"order_id": "x"}}


async def test_401_raises_authentication_error():
    http = MagicMock()
    http.request = AsyncMock(return_value=_mock_response(401))
    client = _make_client(http)
    with pytest.raises(AuthenticationError):
        await client.get("/markets")


async def test_404_raises_market_not_found():
    http = MagicMock()
    http.request = AsyncMock(return_value=_mock_response(404))
    client = _make_client(http)
    with pytest.raises(MarketNotFoundError):
        await client.get("/markets/UNKNOWN")


async def test_400_raises_invalid_order_error():
    http = MagicMock()
    http.request = AsyncMock(return_value=_mock_response(400, {"error": "Insufficient balance"}))
    client = _make_client(http)
    with pytest.raises(InvalidOrderError) as exc_info:
        await client.post("/portfolio/orders", json={})
    assert "Insufficient balance" in str(exc_info.value)


async def test_400_with_message_field_raises_invalid_order():
    http = MagicMock()
    http.request = AsyncMock(return_value=_mock_response(400, {"message": "Bad request"}))
    client = _make_client(http)
    with pytest.raises(InvalidOrderError) as exc_info:
        await client.post("/portfolio/orders", json={})
    assert "Bad request" in str(exc_info.value)


async def test_429_with_no_retries_raises_rate_limit():
    http = MagicMock()
    http.request = AsyncMock(return_value=_mock_response(429, {}, {"Retry-After": "1"}))
    client = _make_client(http, max_retries=0)
    with pytest.raises(RateLimitError):
        await client.get("/markets")


async def test_500_with_no_retries_raises_service_unavailable():
    http = MagicMock()
    http.request = AsyncMock(return_value=_mock_response(500))
    client = _make_client(http, max_retries=0)
    with pytest.raises(ServiceUnavailableError):
        await client.get("/markets")


async def test_500_retries_then_succeeds():
    http = MagicMock()
    http.request = AsyncMock(
        side_effect=[
            _mock_response(500),
            _mock_response(200, {"markets": []}),
        ]
    )
    with patch("asyncio.sleep", new_callable=AsyncMock):
        client = _make_client(http, max_retries=2)
        result = await client.get("/markets")
    assert result == {"markets": []}
    assert http.request.call_count == 2


async def test_429_retries_then_succeeds():
    http = MagicMock()
    http.request = AsyncMock(
        side_effect=[
            _mock_response(429, {}, {"Retry-After": "0"}),
            _mock_response(200, {"data": "ok"}),
        ]
    )
    with patch("asyncio.sleep", new_callable=AsyncMock):
        client = _make_client(http, max_retries=2)
        result = await client.get("/positions")
    assert result == {"data": "ok"}


async def test_network_error_retries_then_raises():
    http = MagicMock()
    http.request = AsyncMock(side_effect=httpx.ConnectError("refused"))
    with patch("asyncio.sleep", new_callable=AsyncMock):
        client = _make_client(http, max_retries=1)
        with pytest.raises(ServiceUnavailableError):
            await client.get("/markets")
    assert http.request.call_count == 2


async def test_network_error_retry_succeeds():
    http = MagicMock()
    http.request = AsyncMock(
        side_effect=[
            httpx.ConnectError("refused"),
            _mock_response(200, {"ok": True}),
        ]
    )
    with patch("asyncio.sleep", new_callable=AsyncMock):
        client = _make_client(http, max_retries=2)
        result = await client.get("/markets")
    assert result == {"ok": True}


async def test_timeout_retries_then_raises():
    http = MagicMock()
    http.request = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
    with patch("asyncio.sleep", new_callable=AsyncMock):
        client = _make_client(http, max_retries=1)
        with pytest.raises(ServiceUnavailableError):
            await client.get("/markets")


def test_is_configured_true_when_both_set():
    http = MagicMock()
    client = KalshiClient("http://base", "key", "pem", http)
    assert client.is_configured() is True


def test_is_configured_false_when_key_empty():
    http = MagicMock()
    client = KalshiClient("http://base", "", "pem", http)
    assert client.is_configured() is False


def test_is_configured_false_when_pem_empty():
    http = MagicMock()
    client = KalshiClient("http://base", "key", "", http)
    assert client.is_configured() is False


async def test_probe_reachable_true_on_any_response():
    http = MagicMock()
    http.get = AsyncMock(return_value=_mock_response(404))
    client = KalshiClient("https://demo-api.kalshi.co/trade-api/v2", "k", "p", http)
    assert await client.probe_reachable() is True


async def test_probe_reachable_false_on_connect_error():
    http = MagicMock()
    http.get = AsyncMock(side_effect=httpx.ConnectError("refused"))
    client = KalshiClient("https://demo-api.kalshi.co/trade-api/v2", "k", "p", http)
    assert await client.probe_reachable() is False


async def test_delete_calls_request_with_delete_method():
    http = MagicMock()
    http.request = AsyncMock(return_value=_mock_response(200, {"order": {}}))
    client = _make_client(http)
    await client.delete("/portfolio/orders/abc")
    call_args = http.request.call_args
    assert call_args[0][0] == "DELETE"
