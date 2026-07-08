"""
Background scheduler: refreshes queue priorities and expires stale entries.

Tests may reset module-level state via _set_state().
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from app.config import Settings
from app import postgres as postgres_module
from app import queue as queue_module

logger = logging.getLogger(__name__)

_last_refresh: Optional[datetime] = None


def _set_state(last_refresh: Optional[datetime]) -> None:
    """For testing only."""
    global _last_refresh
    _last_refresh = last_refresh


def get_last_refresh() -> Optional[datetime]:
    return _last_refresh


async def run_refresh(pool, settings: Settings) -> tuple[int, int]:
    """
    One refresh pass: expire stale entries, recalculate priorities,
    persist to postgres.  Returns (expired_removed, priorities_updated).
    """
    global _last_refresh

    expired = queue_module.expire_stale(settings)
    updated = queue_module.recalculate_priorities(settings)

    if pool is not None:
        try:
            await postgres_module.upsert_entries(pool, queue_module.get_queue())
        except Exception:
            logger.exception("postgres upsert failed during scheduler refresh")

    _last_refresh = datetime.now(timezone.utc)
    logger.info(
        "Queue refresh: expired=%d priorities_updated=%d queue_size=%d",
        expired,
        updated,
        queue_module.queue_size(),
    )
    return expired, updated


async def scheduler_loop(pool, settings: Settings) -> None:
    """
    Periodic refresh loop.  Starts with an initial sleep so the first
    pass does not compete with startup.  POST /queue/refresh triggers an
    immediate pass outside the schedule.
    """
    logger.info(
        "Queue scheduler starting; first refresh in %ds",
        settings.queue_refresh_seconds,
    )
    await asyncio.sleep(settings.queue_refresh_seconds)
    while True:
        try:
            await run_refresh(pool, settings)
        except Exception:
            logger.exception("Scheduler refresh error")
        await asyncio.sleep(settings.queue_refresh_seconds)


async def workflow_loop(pool, http, settings: Settings) -> None:
    """
    Autonomous prediction workflow loop.

    Runs every WORKFLOW_INTERVAL_SECONDS.  Each iteration picks the
    highest-priority QUEUED entry and runs the full predict/evaluate/trade
    cycle.  Skipped entirely when WORKFLOW_ENABLED=false.
    """
    from app import workflow as workflow_module

    logger.info(
        "Workflow loop starting; first iteration in %ds (enabled=%s)",
        settings.workflow_interval_seconds,
        settings.workflow_enabled,
    )
    await asyncio.sleep(settings.workflow_interval_seconds)
    while True:
        if settings.workflow_enabled:
            try:
                await workflow_module.run_exclusive(pool, http, settings)
            except Exception:
                logger.exception("Workflow iteration error")
        await asyncio.sleep(settings.workflow_interval_seconds)
