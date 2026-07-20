"""
PostgreSQL interface for the Reflection Engine.

Reads learning summaries from the `learning` schema (owned by learning-engine).
Writes reflections to the `reflection` schema.
"""

import asyncio
import json
import logging
from typing import Optional

import asyncpg

from app.config import get_settings

logger = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None

_POOL_CONNECT_MAX_ATTEMPTS = 5
_POOL_CONNECT_INITIAL_DELAY = 2.0


async def _create_pool_with_retry(url: str, **pool_kwargs) -> asyncpg.Pool:
    """
    Create the connection pool, retrying transient startup failures.

    Postgres's pg_isready healthcheck can report "accepting connections" a
    moment before the server is ready for new sessions (error 57P03, "the
    database system is starting up") — a real race during container
    restarts.  Without this, that momentary lag permanently disables this
    service's database access until someone notices and restarts it by
    hand.  Retries with exponential backoff (2s, 4s, 8s, 16s ~ 30s total)
    before giving up.
    """
    delay = _POOL_CONNECT_INITIAL_DELAY
    last_exc: Exception | None = None
    for attempt in range(1, _POOL_CONNECT_MAX_ATTEMPTS + 1):
        try:
            return await asyncpg.create_pool(url, **pool_kwargs)
        except Exception as exc:
            last_exc = exc
            if attempt == _POOL_CONNECT_MAX_ATTEMPTS:
                break
            logger.warning(
                "PostgreSQL connection attempt %d/%d failed: %s — retrying in %.0fs",
                attempt, _POOL_CONNECT_MAX_ATTEMPTS, exc, delay,
            )
            await asyncio.sleep(delay)
            delay *= 2
    raise last_exc

_CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS reflection.reflections (
    reflection_id   TEXT        PRIMARY KEY,
    analysis_id     TEXT        NOT NULL,
    generated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    strengths       JSONB       NOT NULL DEFAULT '[]',
    weaknesses      JSONB       NOT NULL DEFAULT '[]',
    patterns        JSONB       NOT NULL DEFAULT '[]',
    recommendations JSONB       NOT NULL DEFAULT '[]'
);
"""


async def _init_connection(conn: asyncpg.Connection) -> None:
    await conn.set_type_codec(
        "jsonb",
        encoder=json.dumps,
        decoder=json.loads,
        schema="pg_catalog",
    )


async def startup() -> None:
    global _pool
    settings = get_settings()
    if not settings.postgres_url:
        logger.warning("POSTGRES_URL not set; database disabled")
        return
    try:
        _pool = await _create_pool_with_retry(
            settings.postgres_url,
            init=_init_connection,
            min_size=1,
            max_size=5,
        )
        async with _pool.acquire() as conn:
            await conn.execute(_CREATE_TABLES)
        logger.info("PostgreSQL pool ready; reflection tables ensured")
    except Exception:
        logger.exception("PostgreSQL connection failed; database disabled")
        _pool = None


async def shutdown() -> None:
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


async def is_reachable() -> bool:
    if _pool is None:
        return False
    try:
        async with _pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        return True
    except Exception:
        return False


async def fetch_summary(analysis_id: str) -> Optional[dict]:
    """Fetch one learning summary by analysis_id. Returns None when not found."""
    if _pool is None:
        return None
    async with _pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT analysis_id, analyzed_at, time_range_start, time_range_end,
                   predictions_analyzed, outcomes_available, accuracy,
                   average_confidence, average_execution_ms,
                   model_breakdown, category_breakdown, observations, diagnostics
            FROM learning.learning_summaries
            WHERE analysis_id = $1
            """,
            analysis_id,
        )
    return dict(row) if row else None


async def fetch_recent_summaries(limit: int = 10) -> list[dict]:
    """Fetch recent learning summaries for pattern detection (DESC order)."""
    if _pool is None:
        return []
    async with _pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT analysis_id, analyzed_at, time_range_start, time_range_end,
                   predictions_analyzed, outcomes_available, accuracy,
                   average_confidence, average_execution_ms,
                   model_breakdown, category_breakdown, observations, diagnostics
            FROM learning.learning_summaries
            ORDER BY analyzed_at DESC
            LIMIT $1
            """,
            limit,
        )
    return [dict(r) for r in rows]


async def persist_reflection(reflection) -> None:
    if _pool is None:
        return
    async with _pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                """
                INSERT INTO reflection.reflections
                    (reflection_id, analysis_id, generated_at,
                     strengths, weaknesses, patterns, recommendations)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                ON CONFLICT (reflection_id) DO NOTHING
                """,
                reflection.reflection_id,
                reflection.analysis_id,
                reflection.generated_at,
                reflection.strengths,
                reflection.weaknesses,
                reflection.patterns,
                reflection.recommendations,
            )
