from typing import Optional

import asyncpg
from pydantic import BaseModel

from app.kalshi_client import KalshiConnectorClient
from app.postgres import is_reachable as postgres_reachable


class HealthStatus(BaseModel):
    status: str
    postgres: bool
    kalshi_connector: bool
    dry_run: bool
    version: str = "0.1.0"


async def get_health(
    pool: Optional[asyncpg.Pool],
    kalshi: KalshiConnectorClient,
    dry_run: bool,
) -> HealthStatus:
    pg_ok = await postgres_reachable(pool)
    kc_ok = await kalshi.is_reachable()
    status = "ok" if pg_ok else "degraded"
    return HealthStatus(
        status=status,
        postgres=pg_ok,
        kalshi_connector=kc_ok,
        dry_run=dry_run,
    )
