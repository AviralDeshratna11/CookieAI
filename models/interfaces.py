"""Typed proposal boundaries. No model receives a database handle."""

from typing import Protocol

from memory.schemas import Extraction, ExtractorContext


class EmbeddingModel(Protocol):
    model_id: str
    version: str
    dimensions: int

    def embed(self, text: str) -> list[float]: ...


class ExtractorModel(Protocol):
    def extract(self, context: ExtractorContext) -> Extraction: ...


class ReasoningModel(Protocol):
    def propose(self, task: str, evidence: list[dict]) -> dict: ...


class EntityModel(Protocol):
    def resolve(self, text: str, candidates: list[dict]) -> list[dict]: ...


class RerankerModel(Protocol):
    def rank(self, query: str, candidates: list[str]) -> list[float]: ...


class ReflectionModel(Protocol):
    def reflect(self, evidence: list[dict]) -> dict: ...
