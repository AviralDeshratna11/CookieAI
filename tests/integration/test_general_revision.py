from uuid import uuid4

from sqlalchemy import func, select

from database import reflection_tables as r
from memory.goals.prospective import ProspectiveService
from memory.reflection.discovery import (
    Counterevidence,
    Discoveries,
    Discovery,
    DiscoveryEngine,
    Reassessment,
)
from memory.schemas import MemoryCreate
from models.reflection import CompatibleReflection, Critique


def test_general_finding_keeps_identity_and_loses_confidence_on_counterevidence(
    service, ctx, monkeypatch
):
    support = []
    counter = []
    for i in range(6):
        support.append(
            service.create(
                ctx.model_copy(update={"session_id": uuid4()}),
                MemoryCreate(
                    text=f"Independent quiet workspace choice {i}", type="PREFERENCE"
                ),
            ).memory_id
        )

    def structured(self, prompt, schema, data, model):
        if schema is Reassessment:
            return Reassessment(supporting_memory_ids=support)
        if schema is Discoveries:
            return Discoveries(
                patterns=[
                    Discovery(
                        statement="Quiet workspaces repeatedly matched the recorded choices.",
                        type="RECURRING_PATTERN",
                        supporting_memory_ids=support,
                        applicability_conditions=["quiet workspace"],
                        limitations=[
                            "Observational sample; independent producers are not established."
                        ],
                    )
                ]
            )
        if schema is Counterevidence:
            return Counterevidence(
                counterexample_memory_ids=counter,
                alternative_explanations=[
                    "Other workspace factors may explain the choices."
                ],
            )
        return Critique(
            verdict="DISPUTED" if counter else "VALIDATED",
            reason="Contrary choices exist."
            if counter
            else "Supplied evidence supports this bounded claim.",
        )

    monkeypatch.setattr(CompatibleReflection, "structured", structured)
    engine = DiscoveryEngine(service)
    first = engine.run(ctx)[0]
    assert first["status"] == "ACTIVE"
    assert ProspectiveService(service).matching(
        ctx, {"context": "quiet workspace selection"}
    )
    for i in range(5):
        counter.append(
            service.create(
                ctx.model_copy(update={"session_id": uuid4()}),
                MemoryCreate(
                    text=f"Recorded contrary workspace selection {i}", type="PREFERENCE"
                ),
            ).memory_id
        )
    revised = engine.run(ctx)[0]
    assert revised["insight_id"] == first["insight_id"]
    assert revised["truth_confidence"] < first["truth_confidence"]
    assert revised["status"] == "DISPUTED"
    assert revised["state_revision"] == 2
    assert len(revised["evidence_revisions"]) == 11
    assert revised["state_history"][0]["status"] == "ACTIVE"
    assert (
        ProspectiveService(service).matching(
            ctx, {"context": "quiet workspace selection"}
        )
        == []
    )
    assert engine.run(ctx) == []
    assert engine.run(ctx) == []
    with service.engine.connect() as db:
        assert (
            db.execute(select(func.count()).select_from(r.insights)).scalar_one() == 1
        )
