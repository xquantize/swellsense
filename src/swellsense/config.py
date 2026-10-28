from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    llm_base_url: str = "http://localhost:11434/v1"
    llm_api_key: SecretStr = SecretStr("ollama")
    llm_model: str = "qwen3:8b"
    llm_reasoning_effort: str | None = None
    http_user_agent: str = (
        "SwellSense/0.1 (learning project; contact: set HTTP_USER_AGENT)"
    )
    http_timeout_s: float = 30
    request_delay_s: float = 1.0
    chunk_words: int = 300
    chunk_overlap_words: int = 50


@lru_cache
def get_settings() -> Settings:
    return Settings()
