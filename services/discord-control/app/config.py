import json
from functools import lru_cache
from typing import Any

from pydantic import field_validator
from pydantic.fields import FieldInfo
from pydantic_settings import BaseSettings, DotEnvSettingsSource, EnvSettingsSource


class _CommaListEnvMixin:
    """
    Bypass pydantic-settings' JSON decoding for allowed_user_ids.

    pydantic-settings treats list[int] as a "complex" type and calls
    json.loads() on the raw env string before any field validator runs.
    A bare integer ("444992730335019019") decodes to int, not list;
    a comma-separated string ("123,456") raises JSONDecodeError.
    This mixin passes the raw string straight through so the field
    validator can parse it correctly.
    """

    def prepare_field_value(
        self,
        field_name: str,
        field: FieldInfo,
        value: str,
        value_is_complex: bool,
    ) -> Any:
        if field_name == "allowed_user_ids" and isinstance(value, str):
            return value
        return super().prepare_field_value(field_name, field, value, value_is_complex)  # type: ignore[misc]


class _PatchedEnvSource(_CommaListEnvMixin, EnvSettingsSource):
    pass


class _PatchedDotEnvSource(_CommaListEnvMixin, DotEnvSettingsSource):
    pass


class Settings(BaseSettings):
    discord_bot_token: str = ""
    discord_guild_id: int = 0
    # Comma-separated list of Discord user snowflake IDs.
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

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: Any,
        env_settings: Any,
        dotenv_settings: Any,
        file_secret_settings: Any,
    ) -> tuple[Any, ...]:
        return (
            init_settings,
            _PatchedEnvSource(settings_cls),
            _PatchedDotEnvSource(settings_cls),
            file_secret_settings,
        )

    @field_validator("allowed_user_ids", mode="before")
    @classmethod
    def _parse_user_ids(cls, v: Any) -> Any:
        if isinstance(v, int):
            # Fallback: pydantic-settings decoded a bare integer as JSON
            return [v]
        if isinstance(v, str):
            v = v.strip()
            if not v:
                return []
            if v.startswith("["):
                return json.loads(v)
            parts = [x.strip() for x in v.split(",")]
            if any(not p for p in parts):
                raise ValueError(
                    "ALLOWED_USER_IDS contains an empty segment — "
                    "check for leading/trailing commas"
                )
            return [int(p) for p in parts]
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()
