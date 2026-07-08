"""
PostgreSQL interface for the Learning Engine.

Reads prediction history from the `prediction` schema (owned by
prediction-api). Writes learning summaries to the `learning` schema.
"""

import json
import logging
from datetime import datetime
from typing import Optional

import asyncpg

from app.config import get_settings
from app.models import AnalysisSummary

logger = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None

_CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS learning.learning_summaries (
    analysis_id             TEXT             PRIMARY KEY,
    analyzed_at             TIMESTAMPTZ      NOT NULL DEFAULT now(),
    time_range_start        TIMESTAMPTZ,
    time_range_end          TIMESTAMPTZ,
    predictions_analyzed    INTEGER          NOT NULL DEFAULT 0,
    outcomes_available      INTEGER          NOT NULL DEFAULT 0,
    accuracy                DOUBLE PRECISION,
    average_confidence      DOUBLE PRECISION,
    average_execution_ms    DOUBLE PRECISION,
    model_breakdown         JSONB            NOT NULL DEFAULT '{}',
    category_breakdown      JSONB            NOT NULL DEFAULT '{}',
    observations            JSONB            NOT NULL DEFAULT '[]',
    diagnostics             JSONB            NOT NULL DEFAULT '{}'
);
ALTER TABLE learning.learning_summaries
    ADD COLUMN IF NOT EXISTS diagnostics JSONB NOT NULL DEFAULT '{}';
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
        _pool = await asyncpg.create_pool(
            settings.postgres_url,
            init=_init_connection,
            min_size=1,
            max_size=5,
        )
        async with _pool.acquire() as conn:
            await conn.execute(_CREATE_TABLES)
        logger.info("PostgreSQL pool ready; learning tables ensured")
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


async def fetch_predictions(
    limit: int = 250,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
) -> list[dict]:
    if _pool is None:
        return []
    async with _pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                req.prediction_id,
                req.question,
                req.category,
                req.market_id,
                req.created_at,
                res.prediction,
                res.confidence,
                res.model,
                res.execution_ms,
                res.search_used,
                out.outcome,
                wr.approved,
                pq.priority_score AS queue_priority_score
            FROM prediction.prediction_requests  req
            JOIN prediction.prediction_responses res USING (prediction_id)
            LEFT JOIN prediction.prediction_outcomes out USING (prediction_id)
            LEFT JOIN LATERAL (
                SELECT approved, queue_id
                FROM queue.workflow_results
                WHERE prediction_id = req.prediction_id
                ORDER BY executed_at DESC NULLS LAST
                LIMIT 1
            ) wr ON true
            LEFT JOIN queue.prediction_queue pq
                ON pq.queue_id::text = wr.queue_id
            WHERE ($1::timestamptz IS NULL OR req.created_at >= $1)
              AND ($2::timestamptz IS NULL OR req.created_at <= $2)
            ORDER BY req.created_at DESC
            LIMIT $3
            """,
            since,
            until,
            limit,
        )
    return [dict(row) for row in rows]


async def persist_summary(summary: AnalysisSummary) -> None:
    if _pool is None:
        return
    async with _pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO learning.learning_summaries
                (analysis_id, analyzed_at, time_range_start, time_range_end,
                 predictions_analyzed, outcomes_available, accuracy,
                 average_confidence, average_execution_ms,
                 model_breakdown, category_breakdown, observations, diagnostics)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
            """,
            summary.analysis_id,
            summary.analyzed_at,
            summary.time_range_start,
            summary.time_range_end,
            summary.predictions_analyzed,
            summary.outcomes_available,
            summary.accuracy,
            summary.average_confidence,
            summary.average_execution_ms,
            summary.model_breakdown,
            summary.category_breakdown,
            summary.observations,
            summary.diagnostics.model_dump(mode="json"),
        )
