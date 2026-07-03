from unittest.mock import AsyncMock, MagicMock

import pytest

from app.positions import Account, Position, _normalize_position, get_account, get_positions


def _raw_position(**overrides) -> dict:
    base = {
        "ticker": "AAPL-24-GT150",
        "position": 10,
        "realized_pnl": 500,
        "unrealized_pnl": 200,
        "market_exposure": 550,
    }
    base.update(overrides)
    return base


# ── _normalize_position ────────────────────────────────────────────────────


def test_normalize_position_positive_is_yes():
    p = _normalize_position(_raw_position(position=5))
    assert p.side == "yes"
    assert p.quantity == 5


def test_normalize_position_negative_is_no():
    p = _normalize_position(_raw_position(position=-3))
    assert p.side == "no"
    assert p.quantity == 3


def test_normalize_position_zero_is_yes():
    p = _normalize_position(_raw_position(position=0))
    assert p.side == "yes"
    assert p.quantity == 0


def test_normalize_position_ticker():
    p = _normalize_position(_raw_position())
    assert p.ticker == "AAPL-24-GT150"


def test_normalize_position_pnl():
    p = _normalize_position(_raw_position(realized_pnl=100, unrealized_pnl=50))
    assert p.realized_pnl == 100
    assert p.unrealized_pnl == 50


def test_normalize_position_market_exposure():
    p = _normalize_position(_raw_position(market_exposure=1000))
    assert p.market_exposure == 1000


def test_normalize_position_missing_fields():
    p = _normalize_position({"ticker": "X"})
    assert p.quantity == 0
    assert p.realized_pnl == 0
    assert p.unrealized_pnl == 0


# ── get_positions ──────────────────────────────────────────────────────────


async def test_get_positions_calls_correct_path():
    client = MagicMock()
    client.get = AsyncMock(return_value={"market_positions": [_raw_position()]})
    result = await get_positions(client)
    client.get.assert_called_once_with("/portfolio/positions")
    assert isinstance(result[0], Position)


async def test_get_positions_returns_empty_list():
    client = MagicMock()
    client.get = AsyncMock(return_value={"market_positions": []})
    result = await get_positions(client)
    assert result == []


async def test_get_positions_normalizes_all():
    client = MagicMock()
    client.get = AsyncMock(return_value={
        "market_positions": [
            _raw_position(position=5),
            _raw_position(ticker="OTHER", position=-2),
        ]
    })
    result = await get_positions(client)
    assert len(result) == 2
    assert result[0].side == "yes"
    assert result[1].side == "no"


# ── get_account ────────────────────────────────────────────────────────────


async def test_get_account_calls_balance_path():
    client = MagicMock()
    client.get = AsyncMock(return_value={"balance": 100000})
    result = await get_account(client)
    client.get.assert_called_once_with("/portfolio/balance")
    assert isinstance(result, Account)


async def test_get_account_balance():
    client = MagicMock()
    client.get = AsyncMock(return_value={"balance": 500000, "portfolio_value": 25000})
    result = await get_account(client)
    assert result.balance == 500000
    assert result.portfolio_value == 25000


async def test_get_account_missing_portfolio_value_defaults_to_zero():
    client = MagicMock()
    client.get = AsyncMock(return_value={"balance": 1000})
    result = await get_account(client)
    assert result.portfolio_value == 0
