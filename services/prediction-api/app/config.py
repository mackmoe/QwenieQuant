from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    ollama_url: str = "http://ollama:11434"
    ollama_model: str = "qwen3:8b"
    ollama_embed_model: str = "nomic-embed-text"
    # qwen3:8b generates a thinking chain before the JSON response; at ~3 tok/s
    # on CPU this can run 2-4 minutes before the first byte is returned.
    ollama_timeout: int = 300

    searxng_url: str = "http://searxng:8080"
    searxng_timeout: float = 10.0
    searxng_max_results: int = 5

    postgres_url: str = ""
    prompt_version: str = "2.0"  # 2.0 = self-knowledge sections (track record, lessons, exemplars)

    confidence_calibration_enabled: bool = True
    confidence_min_history: int = 25
    confidence_max_reduction: float = 0.30

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
