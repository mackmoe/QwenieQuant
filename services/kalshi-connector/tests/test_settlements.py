from unittest.mock import AsyncMock, MagicMock

from app.settlements import Settlement, _normalize_settlement, get_settlements


def _raw_settlement(**overrides) -> dict:
    base = {
        "ticker": "AAPL-24-GT150",
        "revenue": 1000,
        "settled_time": "2024-12-31T20:00:00Z",
        "yes_count": 10,
        "no_count": 0,
    }
    base.update(overrides)
    return base


# ── _normalize_settlement ──────────────────────────────────────────────────


def test_normalize_settlement_ticker():
    s = _normalize_settlement(_raw_settlement())
    assert s.ticker == "AAPL-24-GT150"


def test_normalize_settlement_revenue():
    s = _normalize_settlement(_raw_settlement(revenue=5000))
    assert s.revenue == 5000


def test_normalize_settlement_settled_time_parsed():
    s = _normalize_settlement(_raw_settlement())
    assert s.settled_time is not None
    assert s.settled_time.year == 2024


def test_normalize_settlement_invalid_time_becomes_none():
    s = _normalize_settlement(_raw_settlement(settled_time="bad"))
    assert s.settled_time is None


def test_normalize_settlement_yes_no_counts():
    s = _normalize_settlement(_raw_settlement(yes_count=10, no_count=3))
    assert s.yes_count == 10
    assert s.no_count == 3


def test_normalize_settlement_missing_fields():
    s = _normalize_settlement({"ticker": "X"})
    assert s.revenue == 0
    assert s.settled_time is None
    assert s.yes_count == 0


# ── get_settlements ────────────────────────────────────────────────────────


async def test_get_settlements_calls_correct_path():
    client = MagicMock()
    client.get = AsyncMock(return_value={"settlements": [_raw_settlement()]})
    result = await get_settlements(client)
    client.get.assert_called_once_with("/portfolio/settlements")
    assert isinstance(result[0], Settlement)


async def test_get_settlements_returns_empty_list():
    client = MagicMock()
    client.get = AsyncMock(return_value={"settlements": []})
    result = await get_settlements(client)
    assert result == []


async def test_get_settlements_normalizes_all():
    client = MagicMock()
    client.get = AsyncMock(return_value={
        "settlements": [_raw_settlement(revenue=1000), _raw_settlement(revenue=2000)]
    })
    result = await get_settlements(client)
    assert len(result) == 2
    assert result[0].revenue == 1000
    assert result[1].revenue == 2000
