"""Typed policy merging: file defaults, environment and administrator-managed tenant overrides."""

import os
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Policy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    extraction_threshold: float = Field(default=0.55, ge=0, le=1)
    rolling_messages: int = Field(default=10, ge=1, le=100)
    max_memories_per_turn: int = Field(default=12, ge=1, le=12)
    minimum_candidates: int = Field(default=60, ge=1, le=1000)
    overfetch_multiplier: int = Field(default=4, ge=1, le=20)
    max_memory_tokens: int = Field(default=8000, ge=1000, le=128000)
    graph_max_hops: int = Field(default=3, ge=0, le=3)
    graph_hop_decay: float = Field(default=0.55, ge=0, le=1)
    graph_minimum_activation: float = Field(default=0.10, ge=0, le=1)
    minimum_support: int = Field(default=3, ge=3, le=100)
    serendipity_confidence: float = Field(default=0.65, ge=0, le=1)
    serendipity_novelty: float = Field(default=0.45, ge=0, le=1)
    serendipity_utility: float = Field(default=0.40, ge=0, le=1)
    half_life_days: int = Field(default=180, ge=1)
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

    @model_validator(mode="after")
    def normalized_weights(self):
        allowed = {
            "semantic",
            "keyword",
            "entity",
            "graph",
            "temporal",
            "importance",
            "recency",
            "goal",
            "episode",
            "procedure",
            "associative",
        }
        if set(self.scoring_weights) != allowed or any(
            value < 0 for value in self.scoring_weights.values()
        ):
            raise ValueError(
                "scoring weights require all documented nonnegative signals"
            )
        if abs(sum(self.scoring_weights.values()) - 1) > 1e-6:
            raise ValueError("scoring weights must sum to one")
        return self


def load_policy(path="config/memory.yaml", tenant=None):
    values = {}
    if Path(path).exists():
        values = yaml.safe_load(Path(path).read_text(encoding="utf-8")).get(
            "memory", {}
        )
    values.update(tenant or {})
    for field in Policy.model_fields:
        raw = os.environ.get("MEMORY_" + field.upper())
        if raw is not None:
            values[field] = yaml.safe_load(raw)
    return Policy.model_validate(values)
