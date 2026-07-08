import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

import asyncpg
import httpx
from fastapi import APIRouter, HTTPException

from app.config import Settings
from app.evaluator import run_evaluation
from app.health import HealthStatus, get_health
from app.kalshi_client import KalshiConnectorClient
from app.models import EvaluationRequest, EvaluationResponse
from app.postgres import (
    get_recent_decisions,
    get_today_approved_exposure,
    persist_decision,
)

logger = logging.getLogger(__name__)
router = APIRouter()

_pool: Optional[asyncpg.Pool] = None
_http: Optional[httpx.AsyncClient] = None
_settings: Optional[Settings] = None


def set_dependencies(
    pool: Optional[asyncpg.Pool],
    http: Optional[httpx.AsyncClient],
    settings: Optional[Settings],
) -> None:
    global _pool, _http, _settings
    _pool = pool
    _http = http
    _settings = settings


def _make_decision_id() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    suffix = uuid.uuid4().hex[:8]
    return f"decision_{ts}_{suffix}"


@router.get("/health", response_model=HealthStatus)
async def health_check() -> HealthStatus:
    if _http is None or _settings is None:
        return HealthStatus(
            status="starting",
            postgres=False,
            kalshi_connector=False,
            dry_run=True,
        )
    kalshi = KalshiConnectorClient(_settings.kalshi_connector_url, _http)
    return await get_health(_pool, kalshi, _settings.dry_run)


@router.post("/evaluate", response_model=EvaluationResponse)
async def evaluate(request: EvaluationRequest) -> EvaluationResponse:
    if _settings is None or _http is None:
        raise HTTPException(status_code=503, detail="Service not initialized")

    start = time.monotonic()

    kalshi = KalshiConnectorClient(_settings.kalshi_connector_url, _http)
    account = await kalshi.get_account()
    positions = await kalshi.get_positions()

    today_exposure = (
        await get_today_approved_exposure(_pool) if _pool is not None else 0
    )
    recent_decisions = (
        await get_recent_decisions(_pool) if _pool is not None else []
    )

    response = run_evaluation(
        request, account, positions, today_exposure, recent_decisions, _settings
    )

    elapsed_ms = int((time.monotonic() - start) * 1000)

    if _pool is not None:
        await persist_decision(
            _pool,
            _make_decision_id(),
            request.prediction_id,
            response.approved,
            response.reason,
            response.recommended_contracts,
            response.recommended_max_price,
            elapsed_ms,
            response.risk_checks.model_dump(),
        )

    logger.info(
        "prediction_id=%s approved=%s reason=%s elapsed=%dms",
        request.prediction_id,
        response.approved,
        response.reason,
        elapsed_ms,
    )

    return response
