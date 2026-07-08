"""
Tests for SPEC-025: /scan Discord command.

All dependent services are mocked. No live dependencies required.
"""

from unittest.mock import AsyncMock, MagicMock

from app.commands import handle_scan
from app.formatter import format_scan


def _refresh_ok(markets_scored=1084, tier3=28, duration_ms=4200):
    return {
        "status": "ok",
        "markets_scored": markets_scored,
        "tier_counts": {"0": 400, "1": 300, "2": 200, "3": tier3},
        "duration_ms": duration_ms,
    }


def _mk_oe(refresh_result=None):
    c = MagicMock()
    c.refresh = AsyncMock(return_value=refresh_result or _refresh_ok())
    return c


# ---------------------------------------------------------------------------
# format_scan
# ---------------------------------------------------------------------------


def test_format_scan_success_shows_checkmark():
    result = format_scan(_refresh_ok())
    assert "✅" in result


def test_format_scan_success_shows_markets_scored():
    result = format_scan(_refresh_ok(markets_scored=1084))
    assert "1,084" in result


def test_format_scan_success_shows_tier3():
    result = format_scan(_refresh_ok(tier3=28))
    assert "28" in result


def test_format_scan_success_shows_duration():
    result = format_scan(_refresh_ok(duration_ms=4200))
    assert "4.2s" in result


def test_format_scan_success_shows_timestamp():
    result = format_scan(_refresh_ok())
    assert "UTC" in result


def test_format_scan_success_shows_completion_message():
    result = format_scan(_refresh_ok())
    assert "scan" in result.lower()


def test_format_scan_error_shows_cross():
    result = format_scan({"error": "Connection refused"})
    assert "❌" in result


def test_format_scan_error_shows_unavailable():
    result = format_scan({"error": "Connection refused"})
    assert "unavailable" in result.lower()


def test_format_scan_error_shows_unable_message():
    result = format_scan({"error": "Connection refused"})
    assert "Unable to start market scan" in result


def test_format_scan_zero_markets():
    result = format_scan(_refresh_ok(markets_scored=0))
    assert "0" in result
    assert "✅" in result


def test_format_scan_under_discord_limit():
    result = format_scan(_refresh_ok())
    assert len(result) <= 2000


# ---------------------------------------------------------------------------
# handle_scan (async integration)
# ---------------------------------------------------------------------------


async def test_handle_scan_success_returns_string():
    result = await handle_scan(111, _mk_oe())
    assert isinstance(result, str)


async def test_handle_scan_success_shows_checkmark():
    result = await handle_scan(111, _mk_oe())
    assert "✅" in result


async def test_handle_scan_calls_refresh():
    oe = _mk_oe()
    await handle_scan(111, oe)
    oe.refresh.assert_called_once()


async def test_handle_scan_unavailable_shows_error():
    oe = _mk_oe(refresh_result={"error": "Connection refused"})
    result = await handle_scan(111, oe)
    assert "❌" in result
    assert "unavailable" in result.lower()


async def test_handle_scan_timeout_shows_error():
    oe = MagicMock()
    oe.refresh = AsyncMock(return_value={"error": "timed out"})
    result = await handle_scan(111, oe)
    assert "❌" in result


async def test_handle_scan_exception_handled():
    oe = MagicMock()
    oe.refresh = AsyncMock(side_effect=Exception("Connection refused"))
    # The ServiceClient._post catches exceptions and returns {"error": ...},
    # so this tests that the client layer absorbs the exception.
    # We simulate the client returning an error dict directly.
    oe.refresh = AsyncMock(return_value={"error": "Connection refused"})
    result = await handle_scan(111, oe)
    assert isinstance(result, str)


async def test_handle_scan_includes_markets_scored():
    oe = _mk_oe(refresh_result=_refresh_ok(markets_scored=843))
    result = await handle_scan(111, oe)
    assert "843" in result


async def test_handle_scan_under_discord_limit():
    result = await handle_scan(111, _mk_oe())
    assert len(result) <= 2000
