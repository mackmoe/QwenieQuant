"""PostgreSQL interface for outcome collection in the Kalshi Connector."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import asyncpg

logger = logging.getLogger(__name__)

_CREATE_OUTCOMES = """
CREATE TABLE IF NOT EXISTS prediction.prediction_outcomes (
    prediction_id  TEXT PRIMARY KEY,
    outcome        TEXT,
    resolved_at    TIMESTAMPTZ DEFAULT now()
)
"""

_EXTEND_COLUMNS = [
    "ALTER TABLE prediction.prediction_outcomes ADD COLUMN IF NOT EXISTS market_id TEXT",
    "ALTER TABLE prediction.prediction_outcomes ADD COLUMN IF NOT EXISTS predicted_value TEXT",
    "ALTER TABLE prediction.prediction_outcomes ADD COLUMN IF NOT EXISTS actual_value TEXT",
    "ALTER TABLE prediction.prediction_outcomes ADD COLUMN IF NOT EXISTS prediction_correct BOOLEAN",
    "ALTER TABLE prediction.prediction_outcomes ADD COLUMN IF NOT EXISTS market_close_time TIMESTAMPTZ",
    "ALTER TABLE prediction.prediction_outcomes ADD COLUMN IF NOT EXISTS collected_time TIMESTAMPTZ NOT NULL DEFAULT now()",
    "ALTER TABLE prediction.prediction_outcomes ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}'",
]

_GET_UNRESOLVED = """
SELECT
    req.prediction_id,
    req.market_id,
    req.question,
    res.prediction  AS predicted_value,
    res.confidence
FROM prediction.prediction_requests req
JOIN prediction.prediction_responses res USING (prediction_id)
LEFT JOIN prediction.prediction_outcomes po USING (prediction_id)
WHERE req.market_id IS NOT NULL
  AND po.prediction_id IS NULL
ORDER BY req.created_at ASC
LIMIT $1
"""

_UPSERT_OUTCOME = """
INSERT INTO prediction.prediction_outcomes
    (prediction_id, outcome, resolved_at, market_id, predicted_value,
     actual_value, prediction_correct, market_close_time, collected_time, metadata)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10::jsonb)
ON CONFLICT (prediction_id) DO NOTHING
"""


async def init_pool(url: str) -> asyncpg.Pool:
    """Create pool and extend prediction.prediction_outcomes with outcome columns."""
    pool = await asyncpg.create_pool(url, min_size=1, max_size=3)
    async with pool.acquire() as conn:
        await conn.execute(_CREATE_OUTCOMES)
        for stmt in _EXTEND_COLUMNS:
            await conn.execute(stmt)
    return pool


async def get_unresolved_predictions(pool: asyncpg.Pool, limit: int = 100) -> list[dict]:
    """Return predictions with a market_id that have no recorded outcome yet."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(_GET_UNRESOLVED, limit)
    return [dict(row) for row in rows]


async def persist_outcome(
    pool: asyncpg.Pool,
    *,
    prediction_id: str,
    market_id: str,
    predicted_value: str,
    actual_value: str,
    prediction_correct: bool | None,
    market_close_time: datetime | None,
    metadata: dict,
) -> bool:
    """
    Insert a new outcome row.  Returns True if inserted, False if already exists.
    ON CONFLICT (prediction_id) DO NOTHING prevents duplicate outcomes.
    """
    collected = datetime.now(timezone.utc)
    async with pool.acquire() as conn:
        status = await conn.execute(
            _UPSERT_OUTCOME,
            prediction_id,
            actual_value,      # outcome (legacy column, same as actual_value)
            collected,         # resolved_at (legacy column, same as collected_time)
            market_id,
            predicted_value,
            actual_value,
            prediction_correct,
            market_close_time,
            collected,         # collected_time
            json.dumps(metadata),
        )
    return status == "INSERT 0 1"
