"""
PostgreSQL interface — prediction persistence.

Manages the connection pool lifecycle and the two tables created in the
`prediction` schema during this phase. All functions degrade gracefully
when the pool is unavailable (no POSTGRES_URL set, or DB unreachable).
"""

import json
import logging

import asyncpg

from app.config import get_settings
from app.models import PredictionRequest, PredictionResponse

logger = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None

_CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS prediction.prediction_requests (
    prediction_id   TEXT        PRIMARY KEY,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    question        TEXT        NOT NULL,
    category        TEXT        NOT NULL,
    options         JSONB       NOT NULL,
    context         JSONB       NOT NULL DEFAULT '{}',
    resolution_date DATE,
    market_id       TEXT,
    prompt_version  TEXT        NOT NULL DEFAULT '1.0'
);

CREATE TABLE IF NOT EXISTS prediction.prediction_responses (
    prediction_id     TEXT             PRIMARY KEY,
    created_at        TIMESTAMPTZ      NOT NULL DEFAULT now(),
    prediction        TEXT             NOT NULL,
    confidence        DOUBLE PRECISION NOT NULL,
    reasoning         TEXT             NOT NULL,
    key_factors       JSONB            NOT NULL DEFAULT '[]',
    model             TEXT             NOT NULL,
    execution_ms      INTEGER          NOT NULL,
    search_used       BOOLEAN          NOT NULL DEFAULT FALSE,
    memory_used       BOOLEAN          NOT NULL DEFAULT FALSE,
    validation_status TEXT             NOT NULL DEFAULT 'valid',
    response_payload  JSONB            NOT NULL,
    FOREIGN KEY (prediction_id)
        REFERENCES prediction.prediction_requests (prediction_id)
);

CREATE TABLE IF NOT EXISTS prediction.prediction_outcomes (
    prediction_id   TEXT        PRIMARY KEY,
    outcome         TEXT        NOT NULL,
    resolved_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (prediction_id)
        REFERENCES prediction.prediction_requests (prediction_id)
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
        logger.warning("POSTGRES_URL not set; prediction persistence disabled")
        return
    try:
        _pool = await asyncpg.create_pool(
            settings.postgres_url,
            init=_init_connection,
            min_size=1,
            max_size=10,
        )
        async with _pool.acquire() as conn:
            await conn.execute(_CREATE_TABLES)
        logger.info("PostgreSQL pool ready; prediction tables ensured")
    except Exception:
        logger.exception("PostgreSQL connection failed; persistence disabled")
        _pool = None


async def shutdown() -> None:
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


async def fetch_historical_context(question: str) -> list:
    return []


def _build_response_payload(response: PredictionResponse, calibration_result) -> dict:
    payload = response.model_dump(mode="json")
    if calibration_result is not None and calibration_result.adjusted:
        payload["calibration"] = {
            "original_confidence": calibration_result.original_confidence,
            "calibrated_confidence": calibration_result.calibrated_confidence,
            "reason": calibration_result.reason,
        }
    return payload


async def persist_prediction(
    request: PredictionRequest,
    response: PredictionResponse,
    execution_ms: int,
    *,
    calibration_result=None,
) -> None:
    if _pool is None:
        return
    settings = get_settings()
    async with _pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                """
                INSERT INTO prediction.prediction_requests
                    (prediction_id, question, category, options, context,
                     resolution_date, market_id, prompt_version)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                """,
                response.prediction_id,
                request.question,
                request.category,
                request.options,
                request.context or {},
                request.resolution_date,
                request.market_id,
                settings.prompt_version,
            )
            await conn.execute(
                """
                INSERT INTO prediction.prediction_responses
                    (prediction_id, prediction, confidence, reasoning,
                     key_factors, model, execution_ms, search_used,
                     memory_used, validation_status, response_payload)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                """,
                response.prediction_id,
                response.prediction,
                response.confidence,
                response.reasoning,
                response.key_factors,
                response.model,
                execution_ms,
                response.search_context_used,
                False,
                "valid",
                _build_response_payload(response, calibration_result),
            )


async def fetch_resolved_predictions(limit: int = 500) -> list[dict]:
    """Return resolved predictions (those with an outcome row) for calibration."""
    if _pool is None:
        return []
    async with _pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                req.category,
                req.created_at,
                res.prediction,
                res.confidence,
                res.model,
                out.outcome
            FROM prediction.prediction_outcomes out
            JOIN prediction.prediction_requests req USING (prediction_id)
            JOIN prediction.prediction_responses res USING (prediction_id)
            ORDER BY req.created_at DESC
            LIMIT $1
            """,
            limit,
        )
    return [dict(row) for row in rows]


async def fetch_recent_predictions(limit: int = 10) -> list[dict]:
    if _pool is None:
        return []
    async with _pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                req.prediction_id,
                req.question,
                req.category,
                req.created_at,
                res.prediction,
                res.confidence,
                res.model,
                res.execution_ms
            FROM prediction.prediction_requests req
            JOIN prediction.prediction_responses res USING (prediction_id)
            ORDER BY req.created_at DESC
            LIMIT $1
            """,
            limit,
        )
    return [dict(row) for row in rows]
