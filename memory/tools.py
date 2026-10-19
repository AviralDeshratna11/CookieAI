"""Provider-neutral callable agent tools. Bind trusted identity outside model-generated arguments."""

from uuid import UUID

from memory.context.transfer import ContextRequest, ContextTransferService
from memory.decay.service import DynamicsService
from memory.entities.service import EntityService
from memory.episodes.service import EpisodeService
from memory.experiences.service import ExperienceQuery, ExperienceService
from memory.goals.service import GoalPatch, GoalService
from memory.mutation.engine import MutationRequest
from memory.procedures.service import ProcedureService
from memory.reflection.engine import ReflectionEngine
from memory.schemas import RememberRequest, SearchRequest


class AgentTools:
    def __init__(self, memory, context):
        self.memory, self.ctx = memory, context

    def memory_remember(self, **body):
        return self.memory.remember(self.ctx, RememberRequest.model_validate(body))

    def memory_recall(self, **body):
        return self.memory.search(self.ctx, SearchRequest.model_validate(body))

    def memory_deep_recall(self, **body):
        return self.memory_recall(**{**body, "mode": "DEEP"})

    def memory_search_episode(self, **body):
        return EpisodeService(self.memory).search(
            self.ctx, SearchRequest.model_validate(body)
        )

    def memory_search_experience(self, **body):
        return ExperienceService(self.memory).search(
            self.ctx, ExperienceQuery.model_validate(body)
        )

    def memory_search_procedure(self, **body):
        return ProcedureService(self.memory).search(
            self.ctx, ExperienceQuery.model_validate(body)
        )

    def memory_search_insights(self):
        return ReflectionEngine(self.memory).list(self.ctx)

    def memory_get_context(self, **body):
        return ContextTransferService(self.memory).build(
            self.ctx, ContextRequest.model_validate(body)
        )

    def memory_explain(self, memory_id):
        item = UUID(memory_id)
        return {
            "memory": self.memory.get(self.ctx, item),
            "provenance": self.memory.provenance(self.ctx, item),
        }

    def memory_correct(self, memory_id, candidate, expected_revision):
        return self.memory.mutate(
            self.ctx,
            MutationRequest.model_validate(
                {
                    "candidate": candidate,
                    "target_id": memory_id,
                    "expected_revision": expected_revision,
                    "operation": "CORRECTION",
                }
            ),
        )

    def memory_forget(self, memory_id):
        return self.memory.delete(self.ctx, UUID(memory_id))

    def memory_pin(self, memory_id):
        return DynamicsService(self.memory).pin(self.ctx, UUID(memory_id))

    def entity_search(self, **body):
        return EntityService(self.memory).search(
            self.ctx, SearchRequest.model_validate(body)
        )

    def goal_search(self, query=""):
        return [
            goal
            for goal in GoalService(self.memory).list(self.ctx)
            if query.casefold() in goal["title"].casefold()
        ]

    def goal_update(self, goal_id, **body):
        return GoalService(self.memory).patch(
            self.ctx, UUID(goal_id), GoalPatch.model_validate(body)
        )

    def context_transfer(self, **body):
        return ContextTransferService(self.memory).transfer(
            self.ctx, ContextRequest.model_validate(body)
        )

    def registry(self):
        names = "memory_remember memory_recall memory_deep_recall memory_search_episode memory_search_experience memory_search_procedure memory_search_insights memory_get_context memory_explain memory_correct memory_forget memory_pin entity_search goal_search goal_update context_transfer".split()
        return {name: getattr(self, name) for name in names}
