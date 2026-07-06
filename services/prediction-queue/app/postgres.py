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
