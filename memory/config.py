from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MEMORY_", env_file=".env", extra="ignore"
    )
    database_url: str = (
        "postgresql+psycopg://memory_app:memory-app-local-only@127.0.0.1:55432/memory"
    )
    migration_database_url: str | None = None
    app_password: SecretStr = SecretStr("memory-app-local-only")
    credentials_file: Path = Path("config/credentials.json")
    embedding_backend: str = "hash-test"
    embedding_model: str = "hash-test"
    embedding_version: str = "1"
    embedding_dimensions: int = Field(default=64, ge=8, le=1536)
    provider_base_url: str = "http://localhost:11434/v1"
    provider_api_key: SecretStr = SecretStr("local")
    extraction_model: str = "qwen2.5:7b"
    extraction_response_format: str = "json_schema"
    rolling_messages: int = Field(default=10, ge=1, le=100)
    extraction_threshold: float = Field(default=0.55, ge=0, le=1)
    max_memories_per_turn: int = Field(default=12, ge=1, le=12)
    minimum_candidates: int = Field(default=60, ge=1, le=1000)
    overfetch_multiplier: int = Field(default=4, ge=1, le=20)
    request_timeout_seconds: float = Field(default=60, gt=0, le=300)
    model_response_bytes: int = Field(default=262144, ge=1024, le=1048576)
    max_memory_tokens: int = Field(default=8000, ge=1000, le=128000)
    query_rewriter_backend: str = "local-rule"
    scoring_weights: dict[str, float] = {
        "semantic": 0.27,
        "keyword": 0.11,
        "entity": 0.11,
        "graph": 0.11,
        "temporal": 0.07,
        "importance": 0.08,
        "recency": 0.04,
        "goal": 0.08,
        "episode": 0.05,
        "procedure": 0.04,
        "associative": 0.04,
    }
