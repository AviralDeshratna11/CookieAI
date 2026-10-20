from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import model_validator

from memory.schemas import Field, MemoryCreate, StrictModel


class ToolStep(StrictModel):
    tool: Literal["cookieai_calculate", "cookieai_read_text"]
    arguments: dict = Field(default_factory=dict)
    on_failure: Literal["STOP", "CONTINUE"] = "STOP"

    @model_validator(mode="after")
    def typed_parameters(self):
        key = "expression" if self.tool == "cookieai_calculate" else "path"
        if set(self.arguments) != {key} or not isinstance(self.arguments[key], str):
            raise ValueError("tool parameters do not match the approved schema")
        if not 1 <= len(self.arguments[key]) <= 200:
            raise ValueError("tool parameter exceeds its input bound")
        return self


class VerifierSpec(StrictModel):
    kind: Literal["DECIMAL_RESULT", "TEXT_SHA256", "TEXT_EXISTS", "JSON_FIELDS"]
    step_index: int = Field(default=0, ge=0, le=11)
    expected: str | dict | None = None
    path: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def concrete_criterion(self):
        if self.kind == "DECIMAL_RESULT":
            from decimal import Decimal, InvalidOperation

            try:
                valid = (
                    isinstance(self.expected, str)
                    and Decimal(self.expected).is_finite()
                )
            except InvalidOperation:
                valid = False
            if not valid:
                raise ValueError(
                    "decimal verifier requires a finite expected decimal string"
                )
        elif not self.path:
            raise ValueError("artifact verifier requires an approved relative path")
        if self.kind == "TEXT_SHA256":
            import re

            if not isinstance(self.expected, str) or not re.fullmatch(
                "[0-9a-f]{64}", self.expected
            ):
                raise ValueError("artifact hash must be an exact SHA-256")
        if self.kind == "JSON_FIELDS" and (
            not isinstance(self.expected, dict) or not self.expected
        ):
            raise ValueError(
                "JSON verifier requires nonempty expected top-level fields"
            )
        return self


class TaskInput(StrictModel):
    goal_id: UUID
    objective: str = Field(min_length=1, max_length=2000)
    idempotency_key: str = Field(min_length=1, max_length=128)
    backend: Literal["deterministic", "hermes"] = "deterministic"
    complete_goal_on_success: bool = False
    steps: list[ToolStep] = Field(default_factory=list, max_length=12)
    allowed_tools: list[Literal["cookieai_calculate", "cookieai_read_text"]] = Field(
        min_length=1, max_length=2
    )
    verifier: VerifierSpec
    priority: int = Field(default=5, ge=1, le=9)
    max_runs: int = Field(default=1, ge=1, le=100)
    max_evaluations: int = Field(default=100, ge=1, le=1000)
    max_tool_calls: int = Field(default=12, ge=1, le=30)
    max_model_calls: int = Field(default=6, ge=0, le=12)
    timeout_seconds: int = Field(default=60, ge=1, le=300)
    retry_seconds: int = Field(default=60, ge=10, le=86400)
    repeat_seconds: int | None = Field(default=None, ge=60, le=2592000)
    start_at: datetime | None = None
    deadline: datetime | None = None
    depends_on: list[UUID] = Field(default_factory=list, max_length=20)
    parent_task_id: UUID | None = None
    evidence_ids: list[UUID] = Field(default_factory=list, max_length=30)
    required_procedure_id: UUID | None = None
    procedure_revision: int | None = Field(default=None, ge=1)
    context_signature: dict[str, str] = Field(default_factory=dict, max_length=10)
    preconditions: list[VerifierSpec] = Field(default_factory=list, max_length=5)
    trigger: Literal["MANUAL", "SCHEDULE", "EVENT", "REHEARSAL"] = "MANUAL"
    event_topics: list[str] = Field(default_factory=list, max_length=10)
    evidence_origin: Literal["REAL", "SYNTHETIC", "REHEARSAL"] = "REAL"

    @model_validator(mode="after")
    def bounded_authority(self):
        from memory.context.budget import serialize

        if len(serialize(self.model_dump()).encode("utf-8")) > 32768:
            raise ValueError("task definition exceeds byte budget")
        for value in (self.start_at, self.deadline):
            MemoryCreate.aware_time(value)
        if self.backend == "deterministic" and not self.steps:
            raise ValueError("deterministic tasks require approved steps")
        if any(step.tool not in self.allowed_tools for step in self.steps):
            raise ValueError("planned tool is outside task authority")
        if len(self.steps) > self.max_tool_calls:
            raise ValueError("approved plan exceeds task tool budget")
        if (
            self.backend == "deterministic"
            and self.verifier.kind == "DECIMAL_RESULT"
            and self.verifier.step_index >= len(self.steps)
        ):
            raise ValueError("verifier refers to a missing planned step")
        if self.backend == "hermes" and self.max_model_calls < 1:
            raise ValueError("Hermes needs a positive model-call budget")
        if (self.required_procedure_id is None) != (self.procedure_revision is None):
            raise ValueError(
                "procedure ID and pinned revision must be supplied together"
            )
        if self.trigger == "REHEARSAL" and self.evidence_origin != "REHEARSAL":
            raise ValueError("rehearsal evidence cannot be labeled real")
        if self.trigger == "EVENT" and not self.event_topics:
            raise ValueError("event tasks require explicit topic subscriptions")
        if any(not topic.strip() or len(topic) > 100 for topic in self.event_topics):
            raise ValueError("invalid event topic")
        if any(len(value) > 200 for value in self.context_signature.values()):
            raise ValueError("task context labels exceed their bound")
        if any(spec.kind == "DECIMAL_RESULT" for spec in self.preconditions):
            raise ValueError(
                "preconditions must check independently observable artifacts"
            )
        return self


class TaskControl(StrictModel):
    action: Literal["PAUSE", "RESUME", "CANCEL"]
    expected_revision: int = Field(ge=1)


class Verification(StrictModel):
    verdict: Literal["PASS", "FAIL", "INCONCLUSIVE"]
    criterion: str
    checked_at: datetime
    evidence: dict = Field(default_factory=dict)
    limitations: list[str] = Field(default_factory=list)
    verifier_version: str = "cookieai-deterministic:v1"
