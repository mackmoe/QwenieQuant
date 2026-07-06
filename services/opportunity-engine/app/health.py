from app.kalshi_client import KalshiConnectorClient
from app.models import HealthStatus
from app.postgres import is_reachable as postgres_reachable
from app.scheduler import get_state


async def get_health(pool, kalshi: KalshiConnectorClient) -> HealthStatus:
    pg_ok = await postgres_reachable(pool)
    kc_ok = await kalshi.is_reachable()
    last_scan, markets = get_state()
    tier3 = sum(1 for m in markets if m.assigned_tier == 3)
    status = "ok" if kc_ok else "degraded"
    return HealthStatus(
        status=status,
        kalshi_connector=kc_ok,
        postgres=pg_ok,
        last_scan=last_scan,
        markets_scored=len(markets),
        tier3_candidates=tier3,
    )
