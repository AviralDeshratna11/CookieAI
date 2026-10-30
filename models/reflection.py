"""Separate proposer and falsifier calls; neither has database write access."""

from typing import Literal
from uuid import UUID

from memory.schemas import Field, StrictModel
from models.providers import Provider


class PatternProposal(StrictModel):
    statement: str = Field(min_length=1, max_length=2000)
    supporting_episode_ids: list[UUID] = Field(min_length=1, max_length=30)
    counterexample_episode_ids: list[UUID] = Field(default_factory=list, max_length=30)
    applicability_conditions: list[str] = Field(default_factory=list, max_length=12)
    alternative_explanations: list[str] = Field(default_factory=list, max_length=12)


class Critique(StrictModel):
    verdict: Literal["VALIDATED", "WEAK", "DISPUTED", "REJECTED"]
    reason: str = Field(min_length=1, max_length=2000)


class CompatibleReflection(Provider):
    def review(self, description, support, counter, evidence):
        # Bound the model context; statistical counts still use every eligible source.
        selected_support, selected_counter = support[:20], counter[:10]
        selected = set(selected_support + selected_counter)
        data = {
            "feature": description,
            "population": {
                "failure_episodes": len(support),
                "successful_counterexamples": len(counter),
            },
            "support_ids": selected_support,
            "counterexample_ids": selected_counter,
            "evidence": [
                {"id": str(m.memory_id), "text": m.text[:2500]}
                for m in evidence
                if m.memory_id in selected
            ],
            "task": "Describe only the supplied tool/configuration failure association. Include every supplied support and counterexample ID exactly once. Do not imply causality. Identify applicability and alternative explanations.",
        }
        generator = self.settings.reflection_model or self.settings.extraction_model
        critic = self.settings.critic_model or generator
        proposal = self.structured("reflection_agent", PatternProposal, data, generator)
        if (
            set(proposal.supporting_episode_ids) != set(selected_support)
            or set(proposal.counterexample_episode_ids) != set(selected_counter)
            or len(proposal.supporting_episode_ids) != len(set(selected_support))
            or len(proposal.counterexample_episode_ids) != len(set(selected_counter))
        ):
            raise ValueError(
                "reflection proposal altered the supplied evidence identities"
            )
        critique = self.structured(
            "insight_critic",
            Critique,
            {
                "candidate": proposal.model_dump(mode="json"),
                "independent_evidence_review": data,
                "task": "Try to falsify this association. Review duplicates, confounding, missing baselines, and sample size. Rejection is valid. Never approve causal claims from these observations.",
            },
            critic,
        )
        return (
            proposal,
            critique,
            {
                "generator_model": generator,
                "critic_model": critic,
                "critic_independence": "separate invocation"
                if generator == critic
                else "separate model",
                "prompt_versions": ["reflection_agent:v1", "insight_critic:v1"],
            },
        )
