from pydantic import BaseModel

from app.client import KalshiClient


class HealthStatus(BaseModel):
    status: str
    credentials_configured: bool
    kalshi_reachable: bool
    environment: str
    version: str = "0.1.0"


async def get_health(client: KalshiClient, environment: str) -> HealthStatus:
    configured = client.is_configured()
    reachable = await client.probe_reachable()
    status = "ok" if configured and reachable else "degraded"
    return HealthStatus(
        status=status,
        credentials_configured=configured,
        kalshi_reachable=reachable,
        environment=environment,
    )
