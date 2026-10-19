from memory.schemas import MemoryCreate
from memory.tools import AgentTools


def test_tools_bind_identity_and_entity_search(service, ctx):
    service.create(
        ctx,
        MemoryCreate(text="Alpha uses PostgreSQL", entities=["Alpha", "PostgreSQL"]),
    )
    tools = AgentTools(service, ctx)
    assert len(tools.registry()) == 16
    assert tools.memory_recall(query="Alpha", score_threshold=0)
    assert (
        tools.entity_search(query="Alpha", score_threshold=0.5)[0]["entity"][
            "canonical_name"
        ]
        == "Alpha"
    )
