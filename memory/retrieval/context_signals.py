"""Independent time, goal, episode and procedure candidates over already authorized records."""

from sqlalchemy import select

from database import (
    experience_tables as experiences,
)
from database import (
    learning_tables as episodes,
)
from database import (
    procedure_tables as procedures,
)
from memory.episodes.service import Episode
from memory.experiences.service import fingerprint, structural_similarity
from memory.retrieval.hybrid import terms


def signals(repo, request, corpus):
    permitted = {memory.memory_id: memory for memory in corpus}
    result = {key: {} for key in ("temporal", "goal", "episode", "procedure")}
    if request.time_start or request.time_end:
        for item, memory in permitted.items():
            event = memory.event_at or memory.observed_at
            if (not request.time_start or event >= request.time_start) and (
                not request.time_end or event <= request.time_end
            ):
                result["temporal"][item] = 1
    if request.active_goal_id:
        active = repo.get(request.active_goal_id)
        goal_terms = set(terms(active.canonical_text))
        for item, memory in permitted.items():
            tokens = set(terms(memory.canonical_text))
            value = len(tokens & goal_terms) / max(1, len(goal_terms))
            if value:
                result["goal"][item] = value
    if request.context_signature:
        for row in repo.db.execute(select(episodes.episodes)):
            if row.id not in permitted:
                continue
            value = structural_similarity(
                request.context_signature,
                fingerprint(Episode.model_validate(row.payload)),
            )
            if value:
                result["episode"][row.id] = value
        for row in repo.db.execute(select(experiences.experiences)):
            if row.id not in permitted:
                continue
            value = structural_similarity(
                request.context_signature, row.payload["context_signature"]
            )
            if value:
                result["episode"][row.id] = value
        for row in repo.db.execute(select(procedures.procedures)):
            if row.id not in permitted:
                continue
            value = structural_similarity(
                request.context_signature, row.payload["context_signature"]
            )
            if value:
                result["procedure"][row.id] = value
    return result
