"""
Prediction Workflow: one autonomous prediction cycle per iteration.

Orchestrates the sequence:
  queue.get_next()
    → prediction-api /predict
    → risk-manager /evaluate
    → kalshi-connector /order  (if approved and not dry_run)
    → postgres persist
    → queue.mark_completed()

Error policy:
  Prediction API unavailable → requeue for retry next cycle.
  Risk Manager unavailable   → requeue for retry next cycle.
  Kalshi order fails         → record execution_failed, mark completed.
  Postgres unavailable       → log and continue; queue state still updated.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re as _re
import time
import uuid
from datetime import datetime, timezone

import httpx

from app.config import Settings
from app import postgres as postgres_module
from app import queue as queue_module

logger = logging.getLogger(__name__)

# Kalshi ticker prefixes that unambiguously identify sports markets —
# fallback only; the authoritative category comes from Kalshi's event object
# via the Opportunity Engine (hierarchy: Category → Series → Event → Market).
_SPORTS_TICKER_PREFIXES = (
    "KXMLB", "KXNBA", "KXNFL", "KXNHL",
    "KXSOCCER", "KXCFB", "KXCBB", "KXTENNIS", "KXGOLF", "KXNASCA",
)

_workflow_lock = asyncio.Lock()
_workflow_started_at: datetime | None = None


# ---------------------------------------------------------------------------
# Internal helpers — each is independently mockable in tests
# ---------------------------------------------------------------------------


def _detect_category(title: str, ticker: str) -> str:
    """
    Fallback category inference from ticker prefix and title content.

    Only used when the queue entry's metadata lacks Kalshi's real category
    (e.g. the Opportunity Engine couldn't resolve the market's event).
    Returns Kalshi category names ("Sports", "Financials").
    """
    ticker_upper = ticker.upper()
    if any(ticker_upper.startswith(p) for p in _SPORTS_TICKER_PREFIXES):
        return "Sports"
    title_low = title.lower()
    if "runs scored" in title_low or "wins by" in title_low:
        return "Sports"
    if _re.search(r':\s*\d+\+', title):
        return "Sports"
    return "Financials"


def _format_question(raw_title: str) -> str:
    """Transform a raw Kalshi market title into a natural language question.

    Strips the yes/no directional prefix so the model reasons about the event
    rather than pattern-matching on the word 'yes'.
    """
    title = raw_title.strip()
    low = title.lower()

    if "?" in title:
        return title

    # Strip yes/no directional prefix
    if low.startswith("yes "):
        payload = title[4:].strip()
    elif low.startswith("no "):
        payload = title[3:].strip()
    else:
        payload = title

    # Player prop format: "Freddie Freeman: 1+" → "Will Freddie Freeman record 1 or more?"
    prop_match = _re.match(r'^(.+?):\s*(\d+)\+$', payload)
    if prop_match:
        name = prop_match.group(1).strip()
        threshold = prop_match.group(2)
        return f"Will {name} record {threshold} or more?"

    payload_low = payload.lower()

    # Over/under run totals: "Over 8.5 runs scored" → "Will over 8.5 runs be scored?"
    if payload_low.startswith(("over ", "under ")):
        return f"Will {payload.lower()}?"

    # Run-line / margin format: "Detroit wins by over 1.5 runs"
    if "wins by" in payload_low:
        return f"Will {payload}?"

    # Short strings with no special chars are team/player names → win question
    if len(payload) <= 30 and not any(c in payload for c in (':', '+', '%', '/')):
        return f"Will {payload} win?"

    return f"Will {payload}?"


def _result_id() -> str:
    return f"wf_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}_{uuid.uuid4().hex[:8]}"


def compute_probability(prediction: str, confidence: float) -> float:
    """Convert prediction string + confidence to P(Yes)."""
    pred = prediction.strip().lower()
    if pred in ("yes", "true", "1"):
        return confidence
    if pred in ("no", "false", "0"):
        return max(0.0, 1.0 - confidence)
    return confidence


async def _call_prediction_api(
    http: httpx.AsyncClient,
    settings: Settings,
    entry,
) -> dict:
    raw_title = entry.metadata.get("title", entry.ticker)
    question = _format_question(raw_title)
    if len(question) < 10:
        question = f"Will {raw_title} resolve as Yes?"
    # Kalshi's category (from the market's event) is authoritative;
    # fall back to heuristic detection only when it is missing.
    category = entry.metadata.get("category") or _detect_category(raw_title, entry.ticker)
    resp = await http.post(
        f"{settings.prediction_api_url}/predict",
        json={
            "question": question[:500],
            "category": category,
            "options": ["Yes", "No"],
            "market_id": entry.market_id,
        },
        timeout=330.0,  # qwen3:8b thinking chain can take up to 5 min on CPU
    )
    resp.raise_for_status()
    return resp.json()


async def _fetch_market_price(
    http: httpx.AsyncClient,
    settings: Settings,
    ticker: str,
) -> float | None:
    try:
        resp = await http.get(
            f"{settings.kalshi_connector_url}/market/{ticker}",
            timeout=10.0,
        )
        if resp.status_code == 200:
            data = resp.json()
            yes_bid = data.get("yes_bid") or 0
            yes_ask = data.get("yes_ask") or 0
            if yes_bid and yes_ask:
                return (yes_bid + yes_ask) / 2.0 / 100.0
    except Exception:
        logger.warning("failed to fetch market price for ticker=%s", ticker)
    return None


async def _call_risk_manager(
    http: httpx.AsyncClient,
    settings: Settings,
    prediction_id: str,
    probability: float,
    confidence: float,
    expected_value: float,
    edge: float,
    ticker: str,
    category: str,
) -> dict:
    resp = await http.post(
        f"{settings.risk_manager_url}/evaluate",
        json={
            "prediction_id": prediction_id,
            "probability": round(probability, 4),
            "confidence": round(confidence, 4),
            "expected_value": round(expected_value, 4),
            "edge": round(edge, 4),
            "market_ticker": ticker,
            "market_category": category,
        },
        timeout=30.0,
    )
    resp.raise_for_status()
    return resp.json()


async def _execute_trade(
    http: httpx.AsyncClient,
    settings: Settings,
    ticker: str,
    side: str,
    count: int,
    price: int,
) -> dict | None:
    try:
        resp = await http.post(
            f"{settings.kalshi_connector_url}/order",
            json={
                "ticker": ticker,
                "side": side,
                "action": "buy",
                "count": count,
                "price": price,
                "order_type": "limit",
            },
            timeout=30.0,
        )
        if resp.status_code == 200:
            return resp.json()
        logger.warning(
            "trade execution returned status=%d for ticker=%s", resp.status_code, ticker
        )
        return None
    except Exception:
        logger.exception("trade execution error for ticker=%s", ticker)
        return None


# ---------------------------------------------------------------------------
# Core workflow cycle
# ---------------------------------------------------------------------------


async def run_iteration(
    pool,
    http: httpx.AsyncClient,
    settings: Settings,
) -> dict | None:
    """
    One complete prediction workflow cycle.

    Picks the highest-priority QUEUED entry, runs the full pipeline,
    and marks the entry COMPLETED.  On retryable failures (prediction-api,
    risk-manager unavailable), marks the entry back to QUEUED for the
    next cycle to retry.

    Returns None when the queue is empty, otherwise a dict with at least
    {"status": "completed"|"requeued"|"failed", ...} describing the outcome.
    """
    # Step 1 — pick next candidate
    entry = queue_module.get_next()
    if entry is None:
        return None

    logger.info(
        "opportunity_selected market_id=%s ticker=%s score=%.1f",
        entry.market_id,
        entry.ticker,
        entry.priority_score,
    )

    queue_module.mark_in_progress(entry.market_id)
    t0 = time.monotonic()

    try:
        # Step 1b — skip multi-outcome markets (comma-separated "yes X,yes Y,..." titles)
        title = entry.metadata.get("title", entry.ticker)
        title_low = title.lower()
        if "," in title and (title_low.startswith("yes ") or title_low.startswith("no ")):
            logger.info(
                "multi_outcome_skipped market_id=%s ticker=%s",
                entry.market_id,
                entry.ticker,
            )
            queue_module.mark_completed(entry.market_id)
            return {
                "status": "skipped",
                "reason": "multi_outcome",
                "market_id": entry.market_id,
                "ticker": entry.ticker,
                "title": title,
                "dry_run": settings.dry_run,
            }

        # Step 2 — get AI prediction
        logger.info("prediction_started market_id=%s", entry.market_id)
        try:
            prediction_data = await _call_prediction_api(http, settings, entry)
        except Exception as exc:
            logger.warning(
                "prediction_api_failed market_id=%s error=%s — requeueing",
                entry.market_id,
                exc,
            )
            queue_module.mark_queued(entry.market_id)
            return {
                "status": "requeued",
                "market_id": entry.market_id,
                "ticker": entry.ticker,
                "title": entry.metadata.get("title", entry.ticker),
                "dry_run": settings.dry_run,
            }

        prediction_id = prediction_data.get("prediction_id") or _result_id()
        prediction = prediction_data.get("prediction", "")
        confidence = float(prediction_data.get("confidence", 0.0))
        probability = compute_probability(prediction, confidence)

        raw_title = entry.metadata.get("title", entry.ticker)
        category = entry.metadata.get("category") or _detect_category(raw_title, entry.ticker)

        logger.info(
            "prediction_completed market_id=%s prediction_id=%s prediction=%r confidence=%.2f",
            entry.market_id,
            prediction_id,
            prediction,
            confidence,
        )

        # Fetch market price to compute EV/edge.
        # EV and trade_probability are computed from the perspective of the
        # side being traded (YES when probability >= 0.5, NO otherwise).
        # Without this, NO trades use inverted EV: valid NO edges appear
        # negative (denied) and invalid ones appear positive (approved).
        market_price = await _fetch_market_price(http, settings, entry.ticker)
        side = "yes" if probability >= 0.5 else "no"
        if market_price is not None:
            if side == "yes":
                ev = round(probability - market_price, 4)
                trade_probability = probability
            else:
                # For NO trades: edge = P(No)_model - P(No)_market
                #               = (1 - probability) - (1 - market_price)
                #               = market_price - probability
                ev = round(market_price - probability, 4)
                trade_probability = round(1.0 - probability, 4)
        else:
            ev = 0.0
            trade_probability = probability if side == "yes" else round(1.0 - probability, 4)
            logger.warning(
                "market_price_unavailable ticker=%s — using ev=0 edge=0",
                entry.ticker,
            )

        # Step 3 — evaluate risk
        logger.info("risk_evaluation_started market_id=%s", entry.market_id)
        try:
            risk_data = await _call_risk_manager(
                http, settings,
                prediction_id, trade_probability, confidence, ev, ev,
                entry.ticker, category,
            )
        except Exception as exc:
            logger.warning(
                "risk_manager_failed market_id=%s error=%s — requeueing",
                entry.market_id,
                exc,
            )
            queue_module.mark_queued(entry.market_id)
            return {
                "status": "requeued",
                "market_id": entry.market_id,
                "ticker": entry.ticker,
                "title": entry.metadata.get("title", entry.ticker),
                "prediction": prediction,
                "confidence": confidence,
                "dry_run": settings.dry_run,
            }

        approved = bool(risk_data.get("approved", False))
        risk_reason = risk_data.get("reason", "")
        recommended_contracts = risk_data.get("recommended_contracts")
        recommended_price = risk_data.get("recommended_max_price")

        logger.info(
            "risk_evaluation_completed market_id=%s approved=%s reason=%s",
            entry.market_id,
            approved,
            risk_reason,
        )

        # Steps 4/5 — execute trade or dry-run
        trade_status = "rejected"
        order_data: dict | None = None

        if approved:
            if settings.dry_run:
                trade_status = "dry_run"
                logger.info("trade_skipped_dry_run market_id=%s", entry.market_id)
            else:
                logger.info("trade_approved market_id=%s", entry.market_id)
                qty = int(recommended_contracts) if recommended_contracts else 1
                price = int(recommended_price) if recommended_price else max(1, int(trade_probability * 100))
                order_data = await _execute_trade(
                    http, settings, entry.ticker, side, qty, price
                )
                if order_data:
                    trade_status = "executed"
                    logger.info(
                        "trade_executed market_id=%s order_id=%s",
                        entry.market_id,
                        order_data.get("order_id"),
                    )
                else:
                    trade_status = "execution_failed"
                    logger.warning("trade_execution_failed market_id=%s", entry.market_id)

        # Step 6 — persist result
        duration_ms = int((time.monotonic() - t0) * 1000)
        if pool is not None:
            try:
                await postgres_module.persist_workflow_result(
                    pool,
                    result_id=_result_id(),
                    queue_id=str(entry.queue_id),
                    market_id=entry.market_id,
                    ticker=entry.ticker,
                    prediction_id=prediction_id,
                    prediction=prediction,
                    confidence=confidence,
                    probability=probability,
                    approved=approved,
                    risk_reason=risk_reason,
                    trade_status=trade_status,
                    dry_run=settings.dry_run,
                    order_id=order_data.get("order_id") if order_data else None,
                    duration_ms=duration_ms,
                    metadata={
                        "prediction_data": prediction_data,
                        "risk_data": risk_data,
                        "order_data": order_data,
                    },
                )
            except Exception:
                logger.exception("postgres persist failed for market_id=%s", entry.market_id)

        # Step 7 — mark completed
        logger.info(
            "queue_completed market_id=%s trade_status=%s duration_ms=%d",
            entry.market_id,
            trade_status,
            duration_ms,
        )
        queue_module.mark_completed(entry.market_id)
        return {
            "status": "completed",
            "market_id": entry.market_id,
            "ticker": entry.ticker,
            "title": entry.metadata.get("title", entry.ticker),
            "prediction": prediction,
            "confidence": confidence,
            "risk_approved": approved,
            "risk_reason": risk_reason,
            "trade_status": trade_status,
            "duration_ms": duration_ms,
            "dry_run": settings.dry_run,
        }

    except Exception:
        logger.exception("unexpected workflow error for market_id=%s", entry.market_id)
        queue_module.mark_failed(entry.market_id)
        return {
            "status": "failed",
            "market_id": entry.market_id,
            "ticker": entry.ticker,
            "dry_run": settings.dry_run,
        }


# ---------------------------------------------------------------------------
# Concurrency wrappers
# ---------------------------------------------------------------------------


async def run_exclusive(pool, http: httpx.AsyncClient, settings: Settings) -> None:
    """Scheduler entry point — skips silently if another execution holds the lock."""
    global _workflow_started_at
    if _workflow_lock.locked():
        logger.info("workflow_skipped reason=lock_held")
        return
    async with _workflow_lock:
        _workflow_started_at = datetime.now(timezone.utc)
        try:
            await run_iteration(pool, http, settings)
        finally:
            _workflow_started_at = None


async def run_manual(pool, http: httpx.AsyncClient, settings: Settings) -> dict:
    """API entry point — rejects immediately if another execution is active."""
    global _workflow_started_at
    if _workflow_lock.locked():
        started = _workflow_started_at
        elapsed = None
        if started is not None:
            elapsed = int((datetime.now(timezone.utc) - started).total_seconds())
        return {
            "status": "busy",
            "started_at": started.isoformat() if started else None,
            "elapsed_seconds": elapsed,
        }
    async with _workflow_lock:
        _workflow_started_at = datetime.now(timezone.utc)
        try:
            result = await run_iteration(pool, http, settings)
            if result is None:
                return {"status": "empty"}
            return result
        finally:
            _workflow_started_at = None
