"""Versioned experiment contracts. Approval describes an action, not a balance."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scripts._benchmark_runtime import digest, money_units


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: int = 1


class SourceRecord(Contract):
    source_id: str
    session_id: str
    session_key: str | None = None
    session_date: str
    turn_index: int = Field(ge=0)
    chunk_index: int = Field(ge=0)
    role: Literal["user", "assistant", "system", "tool"]
    text: str
    char_start: int = Field(ge=0)
    char_end: int = Field(ge=0)
    parent_turn_sha256: str

    @model_validator(mode="after")
    def offsets(self):
        if self.char_end - self.char_start != len(self.text):
            raise ValueError("Source offsets do not match exact text")
        return self


class EvidenceBundle(Contract):
    question_id: str
    corpus_sha256: str
    policy_sha256: str
    sources: list[SourceRecord]
    scope: Literal["current_instance"] = "current_instance"


class CostPlan(Contract):
    currency: Literal["USD"] = "USD"
    parent_balance_usd: str = "25"
    reserve_usd: str = "20"
    cumulative_cap_usd: str = "1"
    max_calls: int = Field(default=100, ge=1)
    expected_usd: str | None = None
    upper_bound_usd: str | None = None
    previous_spent_or_reserved_usd: str = "0"
    assumptions: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def bounded(self):
        balance, reserve, cap = map(
            money_units,
            (self.parent_balance_usd, self.reserve_usd, self.cumulative_cap_usd),
        )
        if (
            cap + reserve > balance
            or money_units(self.previous_spent_or_reserved_usd) > cap
        ):
            raise ValueError(
                "Cumulative allocation exceeds balance/reserve or prior spend"
            )
        return self


class EvaluationPlan(Contract):
    experiment_id: str
    dataset_path: str
    dataset_sha256: str
    profile_path: str | None = None
    profile_sha256: str
    code_sha256: str
    question_ids: list[str]
    modes: list[Literal["direct", "hermes", "application", "retrieval-only"]]
    split: Literal["all", "development", "heldout"]
    seed: int = 42
    heldout_fraction: float = 0.2
    dataset_profile: Literal["synthetic", "oracle", "s_cleaned"]
    top_k: int = Field(default=20, ge=1, le=100)
    neighbors: int = Field(default=1, ge=0, le=3)
    cost: CostPlan
    stage: Literal["READY_FOR_REVIEW"] = "READY_FOR_REVIEW"
    development_exposed_ids: list[str] = Field(default_factory=list)
    validation_report_path: str | None = None
    validation_report_sha256: str | None = None
    launch_strategy: Literal["validated", "full_baseline"] = "validated"
    quality_gate: dict = Field(
        default_factory=lambda: {
            "minimum_completion_rate": 0.95,
            "maximum_invalid_final_rate": 0.02,
            "minimum_pilot_questions": 6,
            "note": "Predefined protocol targets; not established by offline fixtures",
        }
    )

    @model_validator(mode="after")
    def identities(self):
        if not self.question_ids or len(self.question_ids) != len(
            set(self.question_ids)
        ):
            raise ValueError("Evaluation IDs must be nonempty and unique")
        if not self.modes or len(set(self.modes)) != len(self.modes):
            raise ValueError("Execution modes must be unique")
        return self

    @property
    def fingerprint(self):
        return digest(self.model_dump(mode="json"))


class Approval(Contract):
    action: Literal["evaluation", "training_upload", "training_submit", "promotion"]
    plan_sha256: str
    approved_by: str = Field(min_length=1)
    approved_at: str
    approval_reference: str = Field(min_length=1)
    expires_at: str

    def require(self, action, fingerprint):
        from datetime import datetime, timezone

        if self.action != action or self.plan_sha256 != fingerprint:
            raise ValueError("Approval does not match this action and frozen plan")
        now = datetime.now(timezone.utc)
        start, end = (
            datetime.fromisoformat(self.approved_at),
            datetime.fromisoformat(self.expires_at),
        )
        if start.tzinfo is None or end.tzinfo is None or not start <= now < end:
            raise ValueError("Approval is expired, future-dated or timezone-ambiguous")


class Checkpoint(Contract):
    base_model: str
    job_id: str
    checkpoint_id: str
    artifact_sha256: str
    inference_model: str
    evaluation_plan_sha256: str
    promoted: bool = False


class StageOutcome(Contract):
    stage: str
    status: Literal["pending", "completed", "failed", "unknown", "blocked", "skipped"]
    artifact_sha256: str | None = None
    error_class: str | None = None


class ComparisonPlan(Contract):
    base_model: str
    checkpoint_model: str
    dataset_sha256: str
    question_ids: list[str]
    effective_policy_sha256: str
    answer_prompt_sha256: str
    response_adapter: str
    judge_route_sha256: str
    minimum_completion: float = Field(default=0.95, ge=0, le=1)
    maximum_invalid_final_rate: float = Field(default=0.02, ge=0, le=1)
    minimum_valid_grades: int = Field(default=30, ge=1)

    @property
    def fingerprint(self):
        return digest(self.model_dump(mode="json"))
