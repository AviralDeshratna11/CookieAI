from uuid import uuid4

from sqlalchemy import select

from database import reflection_tables as r
from memory.reflection.discovery import (
    Counterevidence,
    Discoveries,
    Discovery,
    DiscoveryEngine,
)
from memory.schemas import MemoryCreate, SearchRequest
from models.reflection import CompatibleReflection, Critique


def test_general_discovery_preserves_candidate_state_and_separate_critic(
    service, ctx, monkeypatch
):
    ids = []
    for index in range(4):
        session = ctx.model_copy(update={"session_id": uuid4()})
        ids.append(
            service.create(
                session,
                MemoryCreate(
                    text=f"Observed choice {index}: quiet workspace", type="PREFERENCE"
                ),
            ).memory_id
        )
    stages = []

    def structured(self, prompt, schema, data, model):
        stages.append(prompt)
        if schema is Discoveries:
            return Discoveries(
                patterns=[
                    Discovery(
                        statement="Quiet workspaces were repeatedly chosen.",
                        type="RECURRING_PATTERN",
                        supporting_memory_ids=ids,
                        limitations=["Small attributed sample; no causal conclusion."],
                    )
                ]
            )
        if schema is Counterevidence:
            return Counterevidence(
                alternative_explanations=[
                    "These observations may share an unrecorded context."
                ]
            )
        return Critique(
            verdict="WEAK", reason="Too little independent evidence for generalization."
        )

    monkeypatch.setattr(CompatibleReflection, "structured", structured)
    finding = DiscoveryEngine(service).run(ctx)[0]
    assert stages == ["reflection_agent", "counterexample_finder", "insight_critic"]
    assert finding["status"] == "CANDIDATE"
    assert finding["truth_confidence"] < 0.65
    assert finding["causal"] is False
    assert DiscoveryEngine(service).run(ctx) == []
    assert all(
        str(hit.memory.memory_id) != finding["insight_id"]
        for hit in service.search(
            ctx, SearchRequest(query="quiet workspace", score_threshold=0)
        )
    )
    with service.engine.connect() as db:
        assert db.execute(select(r.insights.c.id)).scalar() is not None
