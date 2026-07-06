from __future__ import annotations

from app import postgres as postgres_module
from app import queue as queue_module
from app import scheduler as scheduler_module
from app.config import Settings
from app.models import HealthStatus


async def get_health(pool, settings: Settings) -> HealthStatus:
    postgres_ok = False
    if pool is not None:
        postgres_ok = await postgres_module.is_reachable(pool)

    active = queue_module.queue_size()
    total = len(queue_module.get_queue())
    status = "ok" if postgres_ok else "degraded"

    return HealthStatus(
        status=status,
        postgres=postgres_ok,
        queue_size=total,
        active_entries=active,
        last_refresh=scheduler_module.get_last_refresh(),
        version=settings.version,
    )
