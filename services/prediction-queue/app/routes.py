from __future__ import annotations

import logging
import time

from fastapi import APIRouter, HTTPException, Query

from app import postgres as postgres_module
from app import queue as queue_module
from app import workflow as workflow_module
from app.config import Settings
from app.health import get_health
from app.models import (
    ACTIVE_STATES,
    AddRequest,
    AddResponse,
    HealthStatus,
    QueueEntry,
    QueueResponse,
    QueueState,
    RefreshResponse,
    RunResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter()

_pool = None
_settings: Settings | None = None
_http = None


def set_dependencies(pool, settings: Settings, http=None) -> None:
    global _pool, _settings, _http
    _pool = pool
    _settings = settings
    _http = http


@router.get("/health", response_model=HealthStatus)
async def health() -> HealthStatus:
    return await get_health(_pool, _settings)


@router.get("/queue", response_model=QueueResponse)
async def get_queue(
    state: QueueState | None = Query(None),
    limit: int = Query(100, ge=1, le=1000),
) -> QueueResponse:
    entries = queue_module.get_queue(state=state, limit=limit)
    total = len(queue_module.get_queue())
    active = queue_module.queue_size()
    by_state = queue_module.get_stats()
    return QueueResponse(
        entries=entries,
        total=total,
        active=active,
        by_state={k: v for k, v in by_state.items()},
        version=_settings.version,
    )


@router.get("/queue/next", response_model=QueueEntry | None)
async def get_next() -> QueueEntry | None:
    return queue_module.get_next()


@router.post("/queue/add", response_model=AddResponse)
async def add_to_queue(request: AddRequest) -> AddResponse:
    if _settings is None:
        raise HTTPException(status_code=503, detail="Service not initialized")
    added, updated, discarded = queue_module.add_or_update(
        request.opportunities, _settings
    )
    if _pool is not None:
        try:
            await postgres_module.upsert_entries(_pool, queue_module.get_queue())
        except Exception:
            logger.warning("postgres upsert failed on /queue/add")
    return AddResponse(
        added=added,
        updated=updated,
        discarded=discarded,
        queue_size=queue_module.queue_size(),
    )


@router.post("/queue/refresh", response_model=RefreshResponse)
async def refresh_queue() -> RefreshResponse:
    if _settings is None:
        raise HTTPException(status_code=503, detail="Service not initialized")
    t0 = time.monotonic()
    expired = queue_module.expire_stale(_settings)
    updated = queue_module.recalculate_priorities(_settings)
    if _pool is not None:
        try:
            await postgres_module.upsert_entries(_pool, queue_module.get_queue())
        except Exception:
            logger.warning("postgres upsert failed on /queue/refresh")
    duration_ms = int((time.monotonic() - t0) * 1000)
    return RefreshResponse(
        status="ok",
        queue_size=queue_module.queue_size(),
        expired_removed=expired,
        priorities_updated=updated,
        duration_ms=duration_ms,
    )


@router.delete("/queue/{market_id}", status_code=204)
async def cancel_entry(market_id: str):
    if not queue_module.cancel(market_id):
        raise HTTPException(
            status_code=404,
            detail=f"Market {market_id!r} not found in active queue",
        )


@router.post("/run", response_model=RunResponse)
async def run_workflow() -> RunResponse:
    if _settings is None:
        raise HTTPException(status_code=503, detail="Service not initialized")
    if _http is None:
        raise HTTPException(status_code=503, detail="HTTP client not available")
    result = await workflow_module.run_manual(_pool, _http, _settings)
    return RunResponse(**result)
