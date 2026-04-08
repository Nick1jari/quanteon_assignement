"""
Centralised configuration via Pydantic Settings.
All tunables are environment-variable-driven and validated at startup.
"""
from functools import lru_cache
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # --- Required ---
    groq_api_key: str

    # --- Optional with defaults ---
    db_path: str = "/app/data/deidentification.db"
    max_file_size_mb: int = 20
    rate_limit_per_minute: int = 20        # per IP, for /deidentify
    log_level: str = "INFO"
    groq_model: str = "llama-3.3-70b-versatile"  # Groq-hosted Llama model
    groq_max_tokens: int = 8096

    # CORS — comma-separated origins in env, parsed to list
    cors_origins: str = "http://localhost:3000,http://localhost:5173"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = v.upper()
        if upper not in allowed:
            raise ValueError(f"log_level must be one of {allowed}")
        return upper

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
