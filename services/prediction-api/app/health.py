from app import ollama
from app.models import HealthStatus


async def get_health() -> HealthStatus:
    ollama_ok = await ollama.is_reachable()
    return HealthStatus(
        status="ok" if ollama_ok else "degraded",
        ollama=ollama_ok,
    )
