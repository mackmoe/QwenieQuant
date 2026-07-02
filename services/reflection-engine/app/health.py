from pydantic import BaseModel

from app import postgres


class HealthStatus(BaseModel):
    status: str
    postgres: bool
    version: str = "0.1.0"


async def get_health() -> HealthStatus:
    reachable = await postgres.is_reachable()
    return HealthStatus(
        status="ok" if reachable else "degraded",
        postgres=reachable,
    )
