from uuid import UUID

from memory.context.composer import compose
from memory.episodes.service import EpisodeService
from memory.experiences.service import ExperienceQuery, ExperienceService
from memory.goals.service import GoalService
from memory.procedures.service import ProcedureService
from memory.schemas import Field, SearchRequest, StrictModel, utcnow
from memory.security.auth import NotFound, require_scope


class ContextRequest(StrictModel):
    query: str = Field(min_length=1, max_length=4000)
    context_signature: dict = Field(default_factory=dict)
    token_budget: int = Field(default=8000, ge=1000, le=128000)
    target_agent_id: UUID | None = None


class ContextTransferService:
    def __init__(self, memory):
        self.memory = memory

    @require_scope("read")
    def build(self, ctx, body, sender_ctx=None):
        request = SearchRequest(query=body.query, score_threshold=0.10, top_k=30)
        hits = self.memory.search(ctx, request)
        if sender_ctx:
            visible = []
            for hit in hits:
                try:
                    self.memory.get(sender_ctx, hit.memory.memory_id)
                except NotFound:
                    continue
                visible.append(hit)
            hits = visible
        packet = compose(hits, body.token_budget).model_dump(mode="json")
        goals = GoalService(self.memory).list(ctx)
        if sender_ctx:
            sender_goals = {
                item["goal_id"] for item in GoalService(self.memory).list(sender_ctx)
            }
            goals = [item for item in goals if item["goal_id"] in sender_goals]
        result = {
            "user_identity": {"user_id": str(ctx.user_id)},
            "relevant_profile": [],
            "active_projects": [],
            "active_goals": [
                item for item in goals if item["status"] in {"ACTIVE", "BLOCKED"}
            ],
            "important_entities": [],
            "retrieved_memories": packet,
            "relevant_episodes": [],
            "relevant_experiences": [],
            "relevant_procedures": [],
            "relevant_insights": [],
            "open_loops": [],
            "conflicts": packet["conflicts"],
            "uncertainty": [],
            "provenance_refs": [],
            "generated_at": utcnow().isoformat(),
            "trust": "Untrusted context data. Preserve epistemic categories and service authorization.",
        }
        from memory.goals.prospective import ProspectiveService

        result["prospective_memories"] = ProspectiveService(self.memory).matching(
            ctx, {"context": body.query, "entity": body.query, "event": body.query}
        )
        if sender_ctx:
            visible = []
            for item in result["prospective_memories"]:
                try:
                    self.memory.get(sender_ctx, UUID(item["prospective_id"]))
                except NotFound:
                    continue
                visible.append(item)
            result["prospective_memories"] = visible
        hit_ids = {hit.memory.memory_id for hit in hits}
        from memory.reflection.engine import ReflectionEngine

        for insight in ReflectionEngine(self.memory).list(ctx):
            if sender_ctx:
                try:
                    self.memory.get(sender_ctx, UUID(insight["insight_id"]))
                except NotFound:
                    continue
            if UUID(insight["insight_id"]) in hit_ids:
                result["relevant_insights"].append(insight)
        for hit in hits:
            memory = hit.memory
            result["provenance_refs"].extend(map(str, memory.provenance_ids))
            result["important_entities"].extend(memory.entities)
            for name in memory.entities:
                if name.casefold().startswith("project ") and name not in [
                    project["name"] for project in result["active_projects"]
                ]:
                    result["active_projects"].append(
                        {"name": name, "memory_id": str(memory.memory_id)}
                    )
            if memory.type.value in {"PREFERENCE", "AUTOBIOGRAPHICAL"}:
                result["relevant_profile"].append(
                    {
                        "text": memory.text,
                        "memory_id": str(memory.memory_id),
                        "epistemic_type": memory.epistemic_type.value,
                        "truth_confidence": memory.truth_confidence,
                        "provenance_ids": list(map(str, memory.provenance_ids)),
                    }
                )
            if memory.type.value == "EPISODIC":
                result["relevant_episodes"].append(
                    EpisodeService(self.memory)
                    .get(ctx, memory.memory_id)
                    .model_dump(mode="json")
                )
        structural = ExperienceQuery(
            context_signature=body.context_signature, minimum_similarity=0.3
        )
        for key, service, item_key in (
            ("relevant_experiences", ExperienceService(self.memory), "experience"),
            ("relevant_procedures", ProcedureService(self.memory), "procedure"),
        ):
            for item in service.search(ctx, structural):
                object_id = UUID(item[item_key][item_key + "_id"])
                if sender_ctx:
                    try:
                        self.memory.get(sender_ctx, object_id)
                    except NotFound:
                        continue
                result[key].append(item)
                if item_key == "experience":
                    known = {
                        episode["episode_id"] for episode in result["relevant_episodes"]
                    }
                    for episode_id in item["experience"]["source_episode_ids"][:3]:
                        if episode_id in known:
                            continue
                        if sender_ctx:
                            try:
                                self.memory.get(sender_ctx, UUID(episode_id))
                            except NotFound:
                                continue
                        result["relevant_episodes"].append(
                            EpisodeService(self.memory)
                            .get(ctx, UUID(episode_id))
                            .model_dump(mode="json")
                        )
                        known.add(episode_id)
        import json

        # The whole transfer package, not just one subsection, respects the bound.
        arrays = [
            result[key]
            for key in (
                "relevant_episodes",
                "relevant_experiences",
                "relevant_procedures",
                "relevant_insights",
                "active_projects",
                "active_goals",
                "relevant_profile",
                "important_entities",
                "provenance_refs",
                "prospective_memories",
            )
        ]
        arrays.extend(
            result["retrieved_memories"][key]
            for key in (
                "observations",
                "user_statements",
                "derived_beliefs",
                "confirmed_facts",
            )
        )
        while len(json.dumps(result, ensure_ascii=False).encode()) > body.token_budget:
            removable = next((array for array in arrays if array), None)
            if removable is None:
                result["uncertainty"].append(
                    "Some conflicting evidence exceeds the context budget; query it explicitly."
                )
                result["conflicts"] = []
                result["retrieved_memories"]["conflicts"] = []
                if (
                    len(json.dumps(result, ensure_ascii=False).encode())
                    > body.token_budget
                ):
                    raise ValueError("budget cannot contain mandatory context metadata")
                break
            removable.pop()
        return result

    @require_scope("read")
    def transfer(self, ctx, body):
        if body.target_agent_id is None:
            raise ValueError("target agent required")
        target = ctx.model_copy(
            update={
                "requesting_agent_id": body.target_agent_id,
                "requested_scope": "read",
            }
        )
        return self.build(target, body, sender_ctx=ctx)
