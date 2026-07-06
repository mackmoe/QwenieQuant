from unittest.mock import AsyncMock, MagicMock

import httpx

from app.kalshi_client import KalshiConnectorClient


def _mock_response(status_code: int, json_data) -> MagicMock:
    response = MagicMock(spec=httpx.Response)
    response.status_code = status_code
    response.json.return_value = json_data
    if status_code >= 400:
        response.raise_for_status.side_effect = httpx.HTTPStatusError(
            f"HTTP {status_code}", request=MagicMock(), response=response
        )
    else:
        response.raise_for_status.return_value = None
    return response


def _client(http: MagicMock) -> KalshiConnectorClient:
    return KalshiConnectorClient("http://kalshi:8003", http)


# ── get_account ─────────────────────────────────────────────────────────────


async def test_get_account_success():
    http = MagicMock()
    http.get = AsyncMock(return_value=_mock_response(200, {"balance": 100_000}))
    result = await _client(http).get_account()
    assert result["balance"] == 100_000


async def test_get_account_http_error_returns_zero_balance():
    http = MagicMock()
    http.get = AsyncMock(return_value=_mock_response(401, {}))
    result = await _client(http).get_account()
    assert result["balance"] == 0
    assert "error" in result


async def test_get_account_connection_error_returns_zero():
    http = MagicMock()
    http.get = AsyncMock(side_effect=httpx.ConnectError("refused"))
    result = await _client(http).get_account()
    assert result["balance"] == 0
    assert "error" in result


async def test_get_account_calls_account_endpoint():
    http = MagicMock()
    http.get = AsyncMock(return_value=_mock_response(200, {"balance": 0}))
    await _client(http).get_account()
    http.get.assert_called_once()
    url = http.get.call_args[0][0]
    assert url.endswith("/account")


# ── get_positions ────────────────────────────────────────────────────────────


async def test_get_positions_success():
    positions = [{"ticker": "T", "side": "yes", "quantity": 5}]
    http = MagicMock()
    http.get = AsyncMock(return_value=_mock_response(200, positions))
    result = await _client(http).get_positions()
    assert len(result) == 1
    assert result[0]["ticker"] == "T"


async def test_get_positions_returns_empty_on_http_error():
    http = MagicMock()
    http.get = AsyncMock(return_value=_mock_response(503, {}))
    result = await _client(http).get_positions()
    assert result == []


async def test_get_positions_returns_empty_on_connection_error():
    http = MagicMock()
    http.get = AsyncMock(side_effect=httpx.ConnectError("refused"))
    result = await _client(http).get_positions()
    assert result == []


# ── is_reachable ─────────────────────────────────────────────────────────────


async def test_is_reachable_true_on_200():
    http = MagicMock()
    http.get = AsyncMock(return_value=_mock_response(200, {}))
    assert await _client(http).is_reachable() is True


async def test_is_reachable_true_on_4xx():
    # 4xx still means the server is up
    http = MagicMock()
    response = MagicMock()
    response.status_code = 404
    http.get = AsyncMock(return_value=response)
    assert await _client(http).is_reachable() is True


async def test_is_reachable_false_on_connection_error():
    http = MagicMock()
    http.get = AsyncMock(side_effect=httpx.ConnectError("refused"))
    assert await _client(http).is_reachable() is False
