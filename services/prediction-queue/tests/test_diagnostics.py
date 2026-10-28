"""Unit tests for the privacy-preserving latest workflow reader."""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.diagnostics import CHECKS, fetch_latest_record, sanitize_record


def sample(**changes):
    row = {
        "executed_at": datetime(2026, 10, 28, 2, 45, tzinfo=timezone.utc),
        "trade_status": "rejected",
        "side": "yes",
        "confidence": 0.72,
        "edge": -0.11,
        "expected_value": -0.13,
        "quote_text": "71",
        "fee_text": "2",
        "approved": False,
        "dry_run": True,
        "risk_checks": '{"confidence":true,"expected_value":false,"edge":false,'
                       '"open_positions":true,"daily_loss":true,"bankroll":true,'
                       '"consecutive_losses":true,"executable_quote":true,'
                       '"direction_bias":true,"token":"SUPER_SECRET"}',
        "market_id": "SECRET_MARKET_ID",
        "risk_reason": "Freeform SECRET_REASON",
        "order_id": "SECRET_ORDER_ID",
    }
    row.update(changes)
    return row


def test_sanitizer_never_includes_unapproved_fields():
    r = sample()
    r["risk_checks"] = {"confidence": True, "expected_value": False, "edge": False}
    result = sanitize_record(r)
    assert result["failed_risk_checks"] == ["expected_value", "edge"]
    assert result["estimated_net_ev"] == -0.13
    assert result["passed_all_risk_checks"] is None
    as_text = str(result)
    assert "SECRET_MARKET_ID" not in as_text
    assert "SECRET_REASON" not in as_text
    assert "SECRET_ORDER_ID" not in as_text
    assert "SUPER_SECRET" not in as_text


def test_sanitizer_unknown_values_fail_closed():
    result = sanitize_record(sample(
        risk_checks={"confidence": False, "unknown": "SECRET"},
        trade_status={"unexpected": "SECRET"},
        edge=float("nan"), expected_value=2.0, confidence=True,
    ))
    assert result["trade_status"] == "unknown"
    assert result["estimated_net_ev"] is None
    assert result["gross_edge"] is None
    assert result["confidence"] is None
    assert result["failed_risk_checks"] == ["confidence"]


@pytest.mark.asyncio
async def test_latest_db_row_is_limited_to_safe_fields():
    row = sample()
    conn = MagicMock()
    conn.fetchrow = AsyncMock(return_value=row)
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=conn)
    context.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire.return_value = context

    result = await fetch_latest_record(pool)
    assert result["quoted_ask_cents"] == 71
    assert result["estimated_taker_fee_cents"] == 2
    assert result["failed_risk_checks"] == ["expected_value", "edge"]
    assert "market_id" not in result
    query = conn.fetchrow.call_args.args[0]
    assert "ORDER BY executed_at DESC" in query
    assert "LIMIT 1" in query
    assert "SELECT *" not in query
    assert "risk_reason" not in query
    assert "order_id" not in query


@pytest.mark.asyncio
async def test_empty_table_returns_none():
    conn = MagicMock()
    conn.fetchrow = AsyncMock(return_value=None)
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=conn)
    context.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire.return_value = context
    assert await fetch_latest_record(pool) is None
