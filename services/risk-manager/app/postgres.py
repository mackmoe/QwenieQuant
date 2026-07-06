import json
import logging
from typing import Optional

import asyncpg

logger = logging.getLogger(__name__)

_CREATE_TABLES = """
CREATE SCHEMA IF NOT EXISTS risk;

CREATE TABLE IF NOT EXISTS risk.trade_decisions (
    decision_id            TEXT        PRIMARY KEY,
    prediction_id          TEXT        NOT NULL,
    timestamp              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    approved               BOOLEAN     NOT NULL,
    reason                 TEXT        NOT NULL,
    recommended_contracts  INTEGER,
    recommended_max_price  INTEGER,
    evaluation_duration_ms INTEGER,
    risk_checks            JSONB       NOT NULL DEFAULT '{}'::jsonb
);
"""


async def _register_codecs(conn: asyncpg.Connection) -> None:
    await conn.set_type_codec(
        "jsonb",
        encoder=json.dumps,
        decoder=json.loads,
        schema="pg_catalog",
    )


async def init_pool(url: str) -> Optional[asyncpg.Pool]:
    if not url:
        return None
    try:
        pool = await asyncpg.create_pool(
            url, min_size=1, max_size=5, init=_register_codecs
        )
        async with pool.acquire() as conn:
            await conn.execute(_CREATE_TABLES)
        logger.info("PostgreSQL pool initialized")
        return pool
    except Exception as exc:
        logger.warning("Failed to initialize PostgreSQL pool: %s", exc)
        return None


async def persist_decision(
    pool: asyncpg.Pool,
    decision_id: str,
    prediction_id: str,
    approved: bool,
    reason: str,
    recommended_contracts: Optional[int],
    recommended_max_price: Optional[int],
    evaluation_duration_ms: int,
    risk_checks: dict,
) -> None:
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO risk.trade_decisions
                  (decision_id, prediction_id, approved, reason,
                   recommended_contracts, recommended_max_price,
                   evaluation_duration_ms, risk_checks)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                """,
                decision_id,
                prediction_id,
                approved,
                reason,
                recommended_contracts,
                recommended_max_price,
                evaluation_duration_ms,
                risk_checks,
            )
    except Exception as exc:
        logger.error("Failed to persist decision %s: %s", decision_id, exc)


async def get_today_approved_exposure(pool: asyncpg.Pool) -> int:
    """
    Sum of (contracts × price) for approved trades stamped today.
    Returns 0 on any database error so evaluation can proceed.
    """
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT COALESCE(
                    SUM(recommended_contracts * recommended_max_price), 0
                ) AS total_exposure
                FROM risk.trade_decisions
                WHERE approved = true
                  AND timestamp >= CURRENT_DATE
                  AND recommended_contracts IS NOT NULL
                  AND recommended_max_price IS NOT NULL
                """
            )
            return int(row["total_exposure"])
    except Exception as exc:
        logger.warning("Failed to query today's exposure: %s", exc)
        return 0


async def get_recent_decisions(pool: asyncpg.Pool, limit: int = 20) -> list[dict]:
    """
    Returns the most recent decisions (newest first) for consecutive-loss check.
    Returns [] on any database error.
    """
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT approved
                FROM risk.trade_decisions
                ORDER BY timestamp DESC
                LIMIT $1
                """,
                limit,
            )
            return [dict(row) for row in rows]
    except Exception as exc:
        logger.warning("Failed to query recent decisions: %s", exc)
        return []


async def is_reachable(pool: Optional[asyncpg.Pool]) -> bool:
    if pool is None:
        return False
    try:
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        return True
    except Exception:
        return False
