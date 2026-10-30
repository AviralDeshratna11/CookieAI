import random

from memory.episodes.service import EpisodeInput, EpisodeService, ToolAttempt
from memory.experiences.service import ExperienceService
from memory.serendipity.engine import SerendipityEngine
from models.reflection import Critique
from models.serendipity import AnalogyProposal, CompatibleSerendipity


def _two_domain_analogy(service, ctx):
    for domain in ("software", "workflow"):
        ids = []
        for index in range(4):
            episode = EpisodeService(service).record(
                ctx,
                EpisodeInput(
                    title=f"{domain} contention {index}",
                    trigger="overload",
                    goal="restore flow",
                    context={
                        "goal_type": "restore_flow",
                        "domain": domain,
                        "error_category": "resource_contention",
                        "environment": "production",
                        "workflow_stage": "execution",
                    },
                    outcome="success",
                    attempts=[
                        ToolAttempt(
                            tool="limiter",
                            intent="reduce load",
                            action="limit concurrency",
                            success=True,
                        )
                    ],
                ),
            )
            ids.append(episode.episode_id)
        ExperienceService(service).compile(ctx, ids)


def test_serendipity_returns_none_without_evidence_and_labels_analogy(service, ctx):
    engine = SerendipityEngine(service, rng=random.Random(7))
    assert engine.run(ctx) == []
    _two_domain_analogy(service, ctx)
    results = engine.run(ctx)
    assert len(results) == 1
    assert results[0]["type"] == "ANALOGY"
    assert results[0]["epistemic_type"] == "HYPOTHESIZED"
    assert results[0]["differences"]["domain"] == ["software", "workflow"] or results[
        0
    ]["differences"]["domain"] == ["workflow", "software"]
    assert results[0]["causality_status"] == "NONE"
    assert results[0]["critic_verdict"] == "VALIDATED"
    assert results[0]["derivation"] == "STRUCTURAL_ANALOGY"


def test_compatible_backend_uses_model_framing_but_not_model_confidence(
    service, ctx, monkeypatch
):
    service.settings.reflection_backend = "compatible"
    service.settings.reflection_model = "test-model"
    _two_domain_analogy(service, ctx)

    def structured(self, prompt, schema, data, model):
        if schema is AnalogyProposal:
            return AnalogyProposal(
                type="TRANSFERABLE_STRATEGY",
                statement="A model-framed account of the shared mitigation.",
                supporting_experience_ids=data["support_ids"],
                counterexample_episode_ids=data["counterexample_ids"],
                applicability_conditions=["Both under sustained load"],
                alternative_explanations=["Coincidental timing"],
            )
        return Critique(verdict="VALIDATED", reason="Independently plausible.")

    monkeypatch.setattr(CompatibleSerendipity, "structured", structured)
    engine = SerendipityEngine(service, rng=random.Random(7))
    results = engine.run(ctx)

    assert len(results) == 1
    assert results[0]["type"] == "TRANSFERABLE_STRATEGY"
    assert results[0]["statement"] == "A model-framed account of the shared mitigation."
    assert results[0]["applicability_conditions"] == ["Both under sustained load"]
    assert results[0]["derivation"] == "STRUCTURAL_AND_LLM"
    assert results[0]["model_review"]["generator_model"] == "test-model"
    # Confidence/novelty stay statistical even though the model supplied framing.
    assert 0 < results[0]["truth_confidence"] <= 1


def test_compatible_backend_model_none_rejects_despite_passing_heuristic_gates(
    service, ctx, monkeypatch
):
    service.settings.reflection_backend = "compatible"
    service.settings.reflection_model = "test-model"
    _two_domain_analogy(service, ctx)

    def structured(self, prompt, schema, data, model):
        if schema is AnalogyProposal:
            return AnalogyProposal(type="NONE")
        return Critique(verdict="VALIDATED", reason="unused")

    monkeypatch.setattr(CompatibleSerendipity, "structured", structured)
    engine = SerendipityEngine(service, rng=random.Random(7))
    assert engine.run(ctx) == []
