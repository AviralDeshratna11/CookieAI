"""Model-assisted framing for serendipitous analogy discovery.

The model only supplies natural-language framing: which of the prompt's
typed categories best fits, the statement text, applicability conditions and
alternative explanations. Confidence, novelty, utility and the support/
counterexample sets stay fully deterministic and statistical, computed by
memory/serendipity/engine.py exactly as in the heuristic-only path. The
critic can only lower a verdict, never raise one — the same invariant
models/reflection.py enforces for ordinary reflection.
"""

from typing import Literal
from uuid import UUID

from memory.schemas import Field, StrictModel
from models.providers import Provider
from models.reflection import Critique

ANALOGY_TYPES = Literal[
    "NONE",
    "ANALOGY",
    "RECURRING_PATTERN",
    "SHARED_FAILURE_MODE",
    "SHARED_SUCCESS_PATTERN",
    "TRANSFERABLE_STRATEGY",
    "POSSIBLE_CORRELATION",
    "TEMPORAL_ASSOCIATION",
    "ENTITY_ASSOCIATION",
    "DEPENDENCY",
]


class AnalogyProposal(StrictModel):
    type: ANALOGY_TYPES
    statement: str = Field(default="", max_length=2000)
    supporting_experience_ids: list[UUID] = Field(default_factory=list, max_length=4)
    counterexample_episode_ids: list[UUID] = Field(default_factory=list, max_length=30)
    applicability_conditions: list[str] = Field(default_factory=list, max_length=12)
    alternative_explanations: list[str] = Field(default_factory=list, max_length=12)


def _describe(experience):
    return {
        "id": str(experience.experience_id),
        "problem_pattern": experience.problem_pattern,
        "successful_actions": experience.successful_actions,
        "failed_actions": experience.failed_actions,
        "outcome_pattern": experience.outcome_pattern,
        "description": experience.description[:2500],
    }


class CompatibleSerendipity(Provider):
    def propose(self, anchor, candidate, differences, support, counter, evidence):
        # Bound the model context; statistical counts still use every eligible source.
        anchor_id, candidate_id = anchor.experience_id, candidate.experience_id
        selected_support = [anchor_id, candidate_id]
        selected_counter = counter[:10]
        data = {
            # The actual text the model reasons over — the prior version only
            # sent bare experience UUIDs here, which is why the model could
            # never find a relationship worth surfacing.
            "anchor": _describe(anchor),
            "candidate": _describe(candidate),
            "differences": differences,
            "population": {
                "supporting_episodes": len(support),
                "counterexample_episodes": len(counter),
            },
            "support_ids": selected_support,
            "counterexample_ids": selected_counter,
            "counterexample_evidence": [
                {"id": str(m.memory_id), "text": m.text[:2500]}
                for m in evidence
                if m.memory_id in set(selected_counter)
            ],
            "task": (
                "Decide whether these two experiences (full text above) share "
                "a real, non-obvious relationship worth surfacing. Return NONE "
                "if not. Include both experience IDs in "
                "supporting_experience_ids exactly once when not NONE, and "
                "every supplied counterexample ID exactly once. Never invent a "
                "relationship or promote it to fact."
            ),
        }
        generator = self.settings.reflection_model or self.settings.extraction_model
        critic = self.settings.critic_model or generator
        proposal = self.structured(
            "serendipity_agent", AnalogyProposal, data, generator
        )
        if proposal.type != "NONE" and (
            set(proposal.supporting_experience_ids) != set(selected_support)
            or set(proposal.counterexample_episode_ids) != set(selected_counter)
            or len(proposal.counterexample_episode_ids) != len(set(selected_counter))
        ):
            raise ValueError(
                "serendipity proposal altered the supplied evidence identities"
            )
        critique = self.structured(
            "insight_critic",
            Critique,
            {
                "candidate": proposal.model_dump(mode="json"),
                "independent_evidence_review": data,
                "task": "Try to falsify this proposed analogy. Review duplicates, "
                "confounding, and coincidence. Rejection is valid. Never approve "
                "causal claims from these observations.",
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
                "prompt_versions": ["serendipity_agent:v1", "insight_critic:v1"],
            },
        )
