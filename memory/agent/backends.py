"""Explicit backend contracts. Importing CookieAI never imports Hermes."""

from typing import Literal, Protocol
from uuid import UUID

from memory.schemas import Field, StrictModel


class ExecutionResult(StrictModel):
    backend: Literal["assistant", "hermes"]
    run_id: UUID
    status: Literal["COMPLETED", "FAILED", "CANCELLED", "UNKNOWN"]
    answer: str = Field(min_length=1, max_length=16000)
    # Tool execution is an observation; no model assertion of task success is accepted.
    task_success: bool | None = None
    observations: list[dict] = Field(default_factory=list, max_length=30)
    usage: dict = Field(default_factory=dict)
    latency_ms: float = Field(default=0, ge=0, allow_inf_nan=False)


class ExecutionBackend(Protocol):
    def run(self, run_id: UUID, message: str, context: dict) -> ExecutionResult: ...
