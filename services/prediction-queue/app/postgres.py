"""PostgreSQL persistence for the prediction queue."""

from __future__ import annotations

import json

import asyncpg

_CREATE_SCHEMA = "CREATE SCHEMA IF NOT EXISTS queue;"

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS queue.prediction_queue (
    queue_id           TEXT PRIMARY KEY,
    market_id          TEXT NOT NULL,
    ticker             TEXT NOT NULL,
    priority_score     DOUBLE PRECISION NOT NULL,
    effective_priority DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    queue_state        TEXT NOT NULL,
    enqueue_time       TIMESTAMPTZ NOT NULL,
    expiration_time    TIMESTAMPTZ,
    last_updated       TIMESTAMPTZ NOT NULL,
    metadata           JSONB NOT NULL DEFAULT '{}'
);
"""

_CREATE_INDEX = """
CREATE UNIQUE INDEX IF NOT EXISTS prediction_queue_market_id_idx
    ON queue.prediction_queue (market_id);
"""

_UPSERT = """
INSERT INTO queue.prediction_queue
    (queue_id, market_id, ticker, priority_score, effective_priority,
     queue_state, enqueue_time, expiration_time, last_updated, metadata)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10::jsonb)
ON CONFLICT (queue_id) DO UPDATE SET
    priority_score     = EXCLUDED.priority_score,
    effective_priority = EXCLUDED.effective_priority,
    queue_state        = EXCLUDED.queue_state,
    expiration_time    = EXCLUDED.expiration_time,
    last_updated       = EXCLUDED.last_updated,
    metadata           = EXCLUDED.metadata;
"""


async def init_pool(url: str) -> asyncpg.Pool:
    pool = await asyncpg.create_pool(url, min_size=1, max_size=5)
    async with pool.acquire() as conn:
        await conn.execute(_CREATE_SCHEMA)
        await conn.execute(_CREATE_TABLE)
        await conn.execute(_CREATE_INDEX)
        await conn.execute(_CREATE_WORKFLOW_TABLE)
    return pool


async def upsert_entries(pool: asyncpg.Pool, entries: list) -> None:
    if not entries:
        return
    rows = [
        (
            e.queue_id,
            e.market_id,
            e.ticker,
            e.priority_score,
            e.effective_priority,
            e.queue_state.value,
            e.enqueue_time,
            e.expiration_time,
            e.last_updated,
            json.dumps(e.metadata),
        )
        for e in entries
    ]
    async with pool.acquire() as conn:
        await conn.executemany(_UPSERT, rows)


async def is_reachable(pool: asyncpg.Pool) -> bool:
    try:
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        return True
    except Exception:
        return False


_CREATE_WORKFLOW_TABLE = """
CREATE TABLE IF NOT EXISTS queue.workflow_results (
    result_id           TEXT PRIMARY KEY,
    queue_id            TEXT NOT NULL,
    market_id           TEXT NOT NULL,
    ticker              TEXT NOT NULL,
    prediction_id       TEXT,
    prediction          TEXT,
    confidence          DOUBLE PRECISION,
    probability         DOUBLE PRECISION,
    market_price        DOUBLE PRECISION,
    expected_value      DOUBLE PRECISION,
    edge                DOUBLE PRECISION,
    side                TEXT,
    approved            BOOLEAN,
    risk_reason         TEXT,
    trade_status        TEXT NOT NULL,
    dry_run             BOOLEAN NOT NULL DEFAULT true,
    order_id            TEXT,
    executed_at         TIMESTAMPTZ NOT NULL,
    duration_ms         INTEGER,
    metadata            JSONB NOT NULL DEFAULT '{}'
);

ALTER TABLE queue.workflow_results ADD COLUMN IF NOT EXISTS market_price DOUBLE PRECISION;
ALTER TABLE queue.workflow_results ADD COLUMN IF NOT EXISTS expected_value DOUBLE PRECISION;
ALTER TABLE queue.workflow_results ADD COLUMN IF NOT EXISTS edge DOUBLE PRECISION;
ALTER TABLE queue.workflow_results ADD COLUMN IF NOT EXISTS side TEXT;
"""

_INSERT_WORKFLOW_RESULT = """
INSERT INTO queue.workflow_results
    (result_id, queue_id, market_id, ticker, prediction_id, prediction,
     confidence, probability, market_price, expected_value, edge, side,
     approved, risk_reason, trade_status, dry_run,
     order_id, executed_at, duration_ms, metadata)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16,
        $17, $18, $19, $20::jsonb)
ON CONFLICT (result_id) DO NOTHING;
"""


async def fetch_activity_stats(pool: asyncpg.Pool, window_minutes: int = 60) -> dict:
    """
    Workflow throughput over a trailing window, for operator dashboards.

    searched joins prediction.prediction_responses (same PostgreSQL
    instance) to report how many processed predictions used SearXNG.
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT count(*)                                            AS processed,
                   count(*) FILTER (WHERE w.approved)                  AS approved,
                   count(*) FILTER (WHERE r.search_used)               AS searched,
                   round(avg(w.duration_ms) / 1000.0, 1)               AS avg_duration_seconds
            FROM queue.workflow_results w
            LEFT JOIN prediction.prediction_responses r USING (prediction_id)
            WHERE w.executed_at > now() - make_interval(mins => $1)
            """,
            window_minutes,
        )
    return {
        "processed": row["processed"],
        "approved": row["approved"],
        "searched": row["searched"],
        "avg_duration_seconds": float(row["avg_duration_seconds"]) if row["avg_duration_seconds"] is not None else None,
    }


async def persist_workflow_result(
    pool: asyncpg.Pool,
    *,
    result_id: str,
    queue_id: str,
    market_id: str,
    ticker: str,
    prediction_id: str | None,
    prediction: str | None,
    confidence: float | None,
    probability: float | None,
    market_price: float | None,
    expected_value: float | None,
    edge: float | None,
    side: str | None,
    approved: bool | None,
    risk_reason: str | None,
    trade_status: str,
    dry_run: bool,
    order_id: str | None,
    duration_ms: int | None,
    metadata: dict,
) -> None:
    from datetime import datetime, timezone

    async with pool.acquire() as conn:
        await conn.execute(
            _INSERT_WORKFLOW_RESULT,
            result_id,
            queue_id,
            market_id,
            ticker,
            prediction_id,
            prediction,
            confidence,
            probability,
            market_price,
            expected_value,
            edge,
            side,
            approved,
            risk_reason,
            trade_status,
            dry_run,
            order_id,
            datetime.now(timezone.utc),
            duration_ms,
            json.dumps(metadata),
        )
