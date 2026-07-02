from app import postgres
from app.models import HealthStatus


async def get_health() -> HealthStatus:
    postgres_ok = await postgres.is_reachable()
    return HealthStatus(
        status="ok" if postgres_ok else "degraded",
        postgres=postgres_ok,
    )
