"""Parameterized handoff contracts attached to existing evidence-backed procedures."""

from typing import Annotated, Literal

from pydantic import Field

from memory.schemas import StrictModel


class HandoffSkill(StrictModel):
    family: Literal["handoff:v1"] = "handoff:v1"
    output_format: Literal["markdown"] = "markdown"
    required_sections: list[
        Literal["summary", "decisions", "deadlines", "questions", "next_actions"]
    ] = Field(
        default_factory=lambda: [
            "summary",
            "decisions",
            "deadlines",
            "questions",
            "next_actions",
        ],
        min_length=1,
        max_length=5,
    )
    minimum_sources: int = Field(default=1, ge=1, le=8)
    required_prefixes: list[Annotated[str, Field(min_length=1, max_length=100)]] = (
        Field(default_factory=list, max_length=5)
    )
    forbidden_phrases: list[Annotated[str, Field(min_length=1, max_length=100)]] = (
        Field(default_factory=list, max_length=5)
    )
    allowed_tools: list[Literal["cookieai_handoff"]] = Field(
        default_factory=lambda: ["cookieai_handoff"], min_length=1, max_length=1
    )
    verifier: Literal["HANDOFF"] = "HANDOFF"
    validation: Literal["USER_CONFIRMED"] = "USER_CONFIRMED"


def applicability(contract, spec, source_texts, *, active=True, revision_matches=True):
    reasons = []
    if not active or not revision_matches:
        reasons.append("Supporting evidence or skill revision is stale")
    if spec.output_format != contract.output_format:
        reasons.append("Output format differs")
    if len(source_texts) < contract.minimum_sources:
        reasons.append("Required source count is not met")
    combined = "\n".join(source_texts).casefold()
    for phrase in contract.forbidden_phrases:
        if phrase.casefold() in combined:
            reasons.append("A declared exception is present")
    missing = [
        prefix
        for prefix in contract.required_prefixes
        if not any(
            line.strip().casefold().startswith(prefix.casefold())
            for text in source_texts
            for line in text.splitlines()
        )
    ]
    if missing:
        return {
            "decision": "incompatible" if reasons else "uncertain",
            "reasons": reasons + ["Required source fields are missing"],
            "missing_fields": missing,
        }
    return {
        "decision": "incompatible" if reasons else "applicable",
        "reasons": reasons or ["Current sources satisfy the confirmed contract"],
        "missing_fields": [],
    }
