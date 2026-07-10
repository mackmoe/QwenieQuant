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

CREATE TABLE IF NOT EXISTS opportunity.market_snapshots (
    ticker          TEXT NOT NULL,
    scan_ts         TIMESTAMPTZ NOT NULL,
    volume          BIGINT NOT NULL DEFAULT 0,
    yes_bid         INTEGER,
    yes_ask         INTEGER,
    open_interest   BIGINT NOT NULL DEFAULT 0,
    priority_score  DOUBLE PRECISION NOT NULL DEFAULT 0,
    rank            INTEGER,
    PRIMARY KEY (ticker, scan_ts)
);

CREATE INDEX IF NOT EXISTS idx_market_snapshots_scan_ts
    ON opportunity.market_snapshots (scan_ts);
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


async def fetch_latest_snapshots(pool: asyncpg.Pool) -> dict[str, dict]:
    """
    Return each ticker's most recent snapshot as {ticker: row_dict}.

    Called at the start of a scan (before this scan's snapshots are written),
    so "latest" is the previous scan — exactly what momentum deltas need.
    """
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT DISTINCT ON (ticker)
                    ticker, scan_ts, volume, yes_bid, yes_ask,
                    open_interest, priority_score, rank
                FROM opportunity.market_snapshots
                ORDER BY ticker, scan_ts DESC
                """
            )
        return {r["ticker"]: dict(r) for r in rows}
    except Exception:
        logger.exception("Failed to fetch market snapshots")
        return {}


async def insert_snapshots(
    pool: asyncpg.Pool,
    markets: list[ScoredMarket],
    scan_ts,
) -> None:
    """Insert one snapshot row per scored market for this scan."""
    if not markets:
        return
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.executemany(
                    """
                    INSERT INTO opportunity.market_snapshots
                        (ticker, scan_ts, volume, yes_bid, yes_ask,
                         open_interest, priority_score, rank)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    ON CONFLICT (ticker, scan_ts) DO NOTHING
                    """,
                    [
                        (
                            m.ticker,
                            scan_ts,
                            m.metadata.get("volume") or 0,
                            _spread_leg(m.metadata, "bid"),
                            _spread_leg(m.metadata, "ask"),
                            m.metadata.get("open_interest") or 0,
                            m.priority_score,
                            m.metadata.get("rank"),
                        )
                        for m in markets
                    ],
                )
    except Exception:
        logger.exception("Failed to insert market snapshots")


def _spread_leg(metadata: dict, leg: str):
    """Snapshot stores raw bid/ask when the scan attached them to metadata."""
    return metadata.get(f"yes_{leg}")


async def prune_snapshots(pool: asyncpg.Pool, retention_days: int) -> None:
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                DELETE FROM opportunity.market_snapshots
                WHERE scan_ts < now() - make_interval(days => $1)
                """,
                retention_days,
            )
    except Exception:
        logger.exception("Failed to prune market snapshots")


async def prune_scores(pool: asyncpg.Pool, retention_days: int) -> None:
    """
    Remove market_scores rows not refreshed within the retention window.

    Rows go stale when a market closes, expires, or stops passing the ingest
    gate — nothing updates them again, so age is the correct removal signal.
    """
    try:
        async with pool.acquire() as conn:
            result = await conn.execute(
                """
                DELETE FROM opportunity.market_scores
                WHERE scoring_timestamp < now() - make_interval(days => $1)
                """,
                retention_days,
            )
        deleted = int(result.split()[-1]) if result else 0
        if deleted:
            logger.info("Pruned %d stale market_scores rows", deleted)
    except Exception:
        logger.exception("Failed to prune market scores")


async def fetch_series_performance(
    pool: asyncpg.Pool,
    min_resolved: int = 20,
    window_days: int = 30,
) -> dict[str, dict]:
    """
    Resolved prediction accuracy per Kalshi series, from the prediction
    schema (cross-schema read; same PostgreSQL instance).

    Returns {series_ticker_prefix: {"resolved": n, "accuracy": 0..1}} for
    series with at least min_resolved outcomes inside the trailing window.
    Feeds the scorer so proven-bad series sink and proven-good series rise.
    """
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT split_part(o.market_id, '-', 1) AS series,
                       count(*)                        AS resolved,
                       avg(CASE WHEN o.prediction_correct THEN 1.0 ELSE 0.0 END)
                           AS accuracy
                FROM prediction.prediction_outcomes o
                JOIN prediction.prediction_responses r USING (prediction_id)
                WHERE o.market_id IS NOT NULL
                  AND r.created_at > now() - make_interval(days => $2)
                GROUP BY 1
                HAVING count(*) >= $1
                """,
                min_resolved,
                window_days,
            )
        return {
            r["series"]: {"resolved": r["resolved"], "accuracy": float(r["accuracy"])}
            for r in rows
            if r["series"]
        }
    except Exception:
        logger.exception("Failed to fetch series performance")
        return {}


async def is_reachable(pool: asyncpg.Pool | None) -> bool:
    if pool is None:
        return False
    try:
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        return True
    except Exception:
        return False
