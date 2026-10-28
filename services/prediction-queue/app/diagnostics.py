"""Strictly sanitized read-only workflow diagnostics for the GitHub bridge.

Do not expose arbitrary trade metadata, titles, identifiers, free-form risk
reasons, order details, or the Kalshi account. Only enumerated data leaves here.
"""
from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite

CHECKS = (
    "confidence", "expected_value", "edge", "open_positions", "daily_loss",
    "bankroll", "consecutive_losses", "executable_quote", "direction_bias",
)
TRADE_STATUSES = {"rejected", "dry_run", "executed", "execution_failed"}


def _num(value, minimum: float, maximum: float) -> float | None:
    if type(value) not in (int, float) or not isfinite(value):
        return None
    value = float(value)
    return round(value, 4) if minimum <= value <= maximum else None


def _int(value, minimum: int, maximum: int) -> int | None:
    if type(value) is not int or not minimum <= value <= maximum:
        return None
    return value


def sanitize_record(row) -> dict | None:
    """Turn a DB row into fixed, low-sensitivity diagnostics."""
    if row is None:
        return None
    row = dict(row)
    raw_checks = row.get("risk_checks")
    checks = raw_checks if isinstance(raw_checks, dict) else {}
    failed_checks = [name for name in CHECKS if checks.get(name) is False]
    all_checks = (all(type(checks.get(name)) is bool for name in CHECKS)
                  and all(checks[name] is True for name in CHECKS))
    stamp = row.get("executed_at")
    if isinstance(stamp, datetime):
        stamp = stamp.astimezone(timezone.utc).isoformat(timespec="seconds")
    else:
        stamp = None
    trade_status = row.get("trade_status")
    return {
        "completed_at_utc": stamp,
        "trade_status": trade_status if trade_status in TRADE_STATUSES else "unknown",
        "side": row.get("side") if row.get("side") in ("yes", "no") else None,
        "confidence": _num(row.get("confidence"), 0, 1),
        "gross_edge": _num(row.get("edge"), -1, 1),
        "estimated_net_ev": _num(row.get("expected_value"), -1, 1),
        "quoted_ask_cents": _int(row.get("quoted_ask_cents"), 1, 99),
        "estimated_taker_fee_cents": _int(row.get("estimated_taker_fee_cents"), 0, 100),
        "risk_approved": row.get("approved") if type(row.get("approved")) is bool else None,
        "passed_all_risk_checks": all_checks if checks else None,
        "failed_risk_checks": failed_checks if checks else None,
        "dry_run": row.get("dry_run") if type(row.get("dry_run")) is bool else None,
    }


async def fetch_latest_record(pool) -> dict | None:
    """Read only one record, including explicitly selected safe JSON fields."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT executed_at, trade_status, side, confidence, edge,
                   expected_value, approved, dry_run,
                   metadata->>'quoted_ask_cents' AS quote_text,
                   metadata->>'estimated_taker_fee_cents' AS fee_text,
                   metadata->'risk_data'->'risk_checks' AS risk_checks
            FROM queue.workflow_results
            ORDER BY executed_at DESC, result_id DESC
            LIMIT 1
            """
        )
    if row is None:
        return None
    result = dict(row)
    # Cast numeric strings only when syntactically exact. No arbitrary
    # metadata objects or free-form errors are passed to the response.
    for source, target in (
        ("quote_text", "quoted_ask_cents"),
        ("fee_text", "estimated_taker_fee_cents"),
    ):
        text = result.pop(source, None)
        result[target] = int(text) if isinstance(text, str) and text.isascii() and text.isdecimal() and len(text) <= 3 else None
    return sanitize_record(result)
