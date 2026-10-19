import pytest
from conftest import RecordingExtractor
from test_discovery_lifecycle import event
from test_postgres import postgres as postgres

from memory.config import Settings
from memory.episodes.service import EpisodeService
from memory.goals.prospective import ProspectiveService
from memory.reflection.engine import ReflectionEngine
from memory.schemas import SearchRequest
from memory.service import MemoryService
from models.providers import HashEmbedding

pytestmark = pytest.mark.postgres


def test_postgres_finding_revision_and_dependent_erasure(postgres, ctx):
    service = MemoryService(
        postgres, HashEmbedding(), RecordingExtractor(), Settings(_env_file=None)
    )
    episodes = EpisodeService(service)
    first = None
    for index in range(12):
        episode = episodes.record(ctx, event(index))
        first = first or episode
    reflection = ReflectionEngine(service)
    active = reflection.run(ctx)[0]
    assert active["status"] == "ACTIVE"
    assert ProspectiveService(service).matching(ctx, {"context": "ReviewTool"})
    for index in range(12, 27):
        episodes.record(ctx, event(index, success=True))
    revised = reflection.run(ctx)[0]
    assert revised["insight_id"] == active["insight_id"]
    assert revised["truth_confidence"] < active["truth_confidence"]
    assert revised["status"] == "DISPUTED"
    source = first.linked_memory_ids[0]
    service.delete(ctx, source)
    assert reflection.list(ctx, include_candidates=True) == []
    assert ProspectiveService(service).matching(ctx, {"context": "ReviewTool"}) == []
    assert all(
        str(hit.memory.memory_id) != active["insight_id"]
        for hit in service.search(
            ctx, SearchRequest(query="ReviewTool", score_threshold=0, top_k=100)
        )
    )
