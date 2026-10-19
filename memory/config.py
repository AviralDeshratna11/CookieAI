from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
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
    embedding_document_prefix: str = ""
    embedding_query_prefix: str = ""
    embedding_dimensions: int = Field(default=64, ge=8, le=4096)
    embedding_input_type_mode: Literal["prefix", "nvidia"] = "prefix"
    provider_base_url: str = "http://localhost:11434/v1"
    provider_api_key: SecretStr = SecretStr("local")
    embedding_provider_base_url: str | None = None
    embedding_provider_api_key: SecretStr | None = None
    provider_enable_thinking: bool | None = None
    extraction_model: str = "qwen2.5:7b"
    extraction_response_format: str = "json_schema"
    reflection_backend: str = "rules"
    general_discovery_enabled: bool = False
    structured_discovery_enabled: bool = True
    candidate_retention_days: int = Field(default=30, ge=1, le=365)
    reflection_model: str | None = None
    critic_model: str | None = None
    reasoning_effort: str | None = None
    reflection_max_model_candidates: int = Field(default=2, ge=0, le=10)
    redis_url: str = "redis://127.0.0.1:6379/0"
    rate_limit_backend: str = "local"
    query_embedding_cache_seconds: float = Field(default=60, ge=0, le=600)
    reflection_interval_seconds: int = Field(default=600, ge=30)
    serendipity_interval_seconds: int = Field(default=3600, ge=60)
    daily_interval_seconds: int = Field(default=86400, ge=60)
    dreamer_interval_seconds: int = Field(default=604800, ge=60)
    worker_event_batch_size: int = Field(default=5, ge=1, le=100)
    worker_stall_seconds: int = Field(default=600, ge=60, le=3600)
    rolling_messages: int = Field(default=10, ge=1, le=100)
    extraction_threshold: float = Field(default=0.55, ge=0, le=1)
    max_memories_per_turn: int = Field(default=12, ge=1, le=12)
    minimum_candidates: int = Field(default=60, ge=1, le=1000)
    overfetch_multiplier: int = Field(default=4, ge=1, le=20)
    request_timeout_seconds: float = Field(default=60, gt=0, le=300)
    model_response_bytes: int = Field(default=262144, ge=1024, le=1048576)
    max_memory_tokens: int = Field(default=8000, ge=1000, le=128000)
    context_tokenizer_file: Path | None = None

    @field_validator("context_tokenizer_file", mode="before")
    @classmethod
    def optional_tokenizer_path(cls, value):
        return None if value == "" else value

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
