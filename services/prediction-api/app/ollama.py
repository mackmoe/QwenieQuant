import httpx

from app.config import get_settings


async def chat(system: str, user: str) -> tuple[str, str | None]:
    """
    Send a chat request to Ollama with format=json enforced.

    Returns (content, thinking) where content is the raw JSON string from
    the model and thinking is the model's reasoning chain (qwen3:8b emits
    this as a separate field; other models return None).
    """
    settings = get_settings()
    payload = {
        "model": settings.ollama_model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "format": "json",
    }
    async with httpx.AsyncClient(timeout=settings.ollama_timeout) as client:
        response = await client.post(
            f"{settings.ollama_url}/api/chat", json=payload
        )
        response.raise_for_status()
        data = response.json()

    content: str = data["message"]["content"]
    thinking: str | None = data.get("thinking")
    return content, thinking


async def is_reachable() -> bool:
    settings = get_settings()
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(f"{settings.ollama_url}/api/tags")
            return response.status_code == 200
    except Exception:
        return False
