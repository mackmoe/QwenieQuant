import json
import logging

import asyncpg

from app.config import get_settings
from app.models import ScoredMarket

logger = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None

_CREATE_TABLES = """
CREATE SCHEMA IF NOT EXISTS opportunity;

CREATE TABLE IF NOT EXISTS opportunity.market_scores (
    market_id           TEXT PRIMARY KEY,
    ticker              TEXT NOT NULL,
    title               TEXT NOT NULL DEFAULT '',
    priority_score      DOUBLE PRECISION NOT NULL,
    assigned_tier       INTEGER NOT NULL,
    scoring_timestamp   TIMESTAMPTZ NOT NULL,
    metadata            JSONB NOT NULL DEFAULT '{}'
);
"""


async def _init_connection(conn: asyncpg.Connection) -> None:
    await conn.set_type_codec(
        "jsonb",
        encoder=json.dumps,
        decoder=json.loads,
        schema="pg_catalog",
    )


async def init_pool(url: str) -> asyncpg.Pool | None:
    if not url:
        logger.warning("POSTGRES_URL not set; opportunity persistence disabled")
        return None
    try:
        pool = await asyncpg.create_pool(
            url,
            init=_init_connection,
            min_size=1,
            max_size=5,
        )
        async with pool.acquire() as conn:
            await conn.execute(_CREATE_TABLES)
        logger.info("PostgreSQL pool ready; opportunity tables ensured")
        return pool
    except Exception:
        logger.exception("PostgreSQL connection failed; persistence disabled")
        return None


async def upsert_scores(
    pool: asyncpg.Pool,
    markets: list[ScoredMarket],
) -> None:
    """Upsert all scored markets. Silently logs errors."""
    if not markets:
        return
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.executemany(
                    """
                    INSERT INTO opportunity.market_scores
                        (market_id, ticker, title, priority_score,
                         assigned_tier, scoring_timestamp, metadata)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    ON CONFLICT (market_id) DO UPDATE SET
                        ticker            = EXCLUDED.ticker,
                        title             = EXCLUDED.title,
                        priority_score    = EXCLUDED.priority_score,
                        assigned_tier     = EXCLUDED.assigned_tier,
                        scoring_timestamp = EXCLUDED.scoring_timestamp,
                        metadata          = EXCLUDED.metadata
                    """,
                    [
                        (
                            m.market_id,
                            m.ticker,
                            m.title,
                            m.priority_score,
                            m.assigned_tier,
                            m.scoring_timestamp,
                            m.metadata,
                        )
                        for m in markets
                    ],
                )
    except Exception:
        logger.exception("Failed to persist market scores")


async def is_reachable(pool: asyncpg.Pool | None) -> bool:
    if pool is None:
        return False
    try:
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        return True
    except Exception:
        return False
