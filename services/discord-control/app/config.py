import json
from functools import lru_cache
from typing import Any

from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    discord_bot_token: str = ""
    discord_guild_id: int = 0
    # Comma-separated or JSON-array list of Discord user snowflake IDs.
    # Example: ALLOWED_USER_IDS=123456789012345678,987654321098765432
    allowed_user_ids: list[int] = []

    prediction_api_url: str = "http://prediction-api:8000"
    learning_engine_url: str = "http://learning-engine:8001"
    reflection_engine_url: str = "http://reflection-engine:8002"
    ollama_url: str = "http://ollama:11434"
    searxng_url: str = "http://searxng:8080"

    # Default timeout for service health checks and /analyze, /reflect.
    # /predict uses its own 330 s override (qwen3:8b thinking chain).
    http_timeout: float = 60.0

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    @field_validator("allowed_user_ids", mode="before")
    @classmethod
    def _parse_user_ids(cls, v: Any) -> Any:
        if isinstance(v, str):
            v = v.strip()
            if not v:
                return []
            if v.startswith("["):
                return json.loads(v)
            return [int(x.strip()) for x in v.split(",") if x.strip()]
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()
