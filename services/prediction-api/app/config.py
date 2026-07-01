from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    ollama_url: str = "http://ollama:11434"
    ollama_model: str = "qwen3:8b"
    ollama_embed_model: str = "nomic-embed-text"
    # qwen3:8b generates a thinking chain before the JSON response; at ~3 tok/s
    # on CPU this can run 2-4 minutes before the first byte is returned.
    ollama_timeout: int = 300

    postgres_url: str = ""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
