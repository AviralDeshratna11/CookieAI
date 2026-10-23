import hashlib
import json
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from apps.api.main import create_app
from database import autonomy_tables as a
from memory.autonomy.contracts import TaskControl
from memory.autonomy.handoff import HandoffSpec, safe_path, workspace_for
from memory.autonomy.portal import BriefInput, Portal, SkillConfirmation, SourceInput
from memory.autonomy.service import TaskSupervisor
from memory.episodes.service import EpisodeInput, EpisodeService, ToolAttempt
from memory.experiences.service import ExperienceService
from memory.goals.service import GoalInput, GoalService
from memory.mutation.engine import MutationRequest
from memory.procedures.service import ProcedureCompile, ProcedureService
from memory.procedures.skills import HandoffSkill, applicability
from memory.schemas import MemoryCreate
from memory.security.auth import AccessDenied, Authenticator, Conflict, Credential
from memory.security.disclosure import (
    DisclosureChange,
    change_policy,
    disclosure_scope,
    policy,
)
from models.providers import CompatibleEmbedding, Provider


@pytest.fixture
def portal(service, ctx, tmp_path):
    service.settings.autonomy_enabled = True
    service.settings.autonomy_allowed_agents = [str(ctx.requesting_agent_id)]
    service.settings.handoff_enabled = True
    service.settings.hermes_workspace = tmp_path
    return Portal(service)


def source(portal, ctx, text="Decision: Use PostgreSQL.\nNext: Review the handoff."):
    return UUID(
        portal.add_source(ctx, SourceInput(title="Cedar notes", content=text))[
            "source_id"
        ]
    )


def brief(portal, ctx, ids, **changes):
    goal = GoalService(portal.memory).create(
        ctx, GoalInput(title="Prepare project handoff")
    )
    return BriefInput(
        project="Cedar",
        source_ids=ids,
        goal_id=UUID(goal["goal_id"]),
        idempotency_key=uuid4().hex,
        **changes,
    )


def test_handoff_end_to_end_idempotency_verifier_and_artifact_acl(portal, ctx, engine):
    identity = source(portal, ctx)
    body = brief(portal, ctx, [identity])
    task = portal.submit(ctx, body)
    assert portal.submit(ctx, body)["replayed"]
    supervisor = TaskSupervisor(portal.memory)
    result = supervisor.process(ctx, UUID(task["task_id"]))
    assert result["status"] == "COMPLETED", result
    run_id = UUID(result["run_id"])
    artifact = portal.artifact(ctx, UUID(task["task_id"]), run_id)
    assert "Use PostgreSQL" in artifact["markdown"]
    assert artifact["disclosure"]["sent"] is False
    assert result["verification"]["verdict"] == "PASS"
    assert supervisor.process(ctx, UUID(task["task_id"]))["status"] == "COMPLETED"
    other = ctx.model_copy(update={"requesting_agent_id": uuid4()})
    with pytest.raises(AccessDenied):
        portal.artifact(other, UUID(task["task_id"]), run_id)
    path = workspace_for(portal.memory, ctx) / f"outputs/{run_id}.json"
    path.write_text("tampered")
    with pytest.raises(Conflict):
        portal.artifact(ctx, UUID(task["task_id"]), run_id)
    with engine.connect() as db:
        row = db.execute(select(a.runs)).mappings().one()
    assert row["payload"]["observations"][0]["result"]["sha256"]


def test_changed_source_and_cancelled_task_do_not_write(portal, ctx):
    identity = source(portal, ctx)
    task = portal.submit(ctx, brief(portal, ctx, [identity]))
    path = workspace_for(portal.memory, ctx) / f"inputs/{identity}.txt"
    path.write_text("changed without approval")
    result = TaskSupervisor(portal.memory).process(ctx, UUID(task["task_id"]))
    assert (
        result["status"] == "WAITING" and result["reason"] == "ApprovalRequiresReview"
    )
    assert not list(workspace_for(portal.memory, ctx).glob("outputs/*.json"))
    identity2 = source(portal, ctx, "Next: A distinct task")
    task2 = portal.submit(ctx, brief(portal, ctx, [identity2]))
    supervisor = TaskSupervisor(portal.memory)
    supervisor.control(
        ctx, UUID(task2["task_id"]), TaskControl(action="CANCEL", expected_revision=1)
    )
    assert supervisor.process(ctx, UUID(task2["task_id"]))["status"] == "CANCELLED"


def test_source_correction_invalidates_approved_task(portal, ctx):
    identity = source(portal, ctx)
    task = portal.submit(ctx, brief(portal, ctx, [identity]))
    portal.memory.mutate(
        ctx,
        MutationRequest(
            operation="CORRECTION",
            target_id=identity,
            expected_revision=1,
            candidate=MemoryCreate(
                text="Decision: PostgreSQL approval withdrawn.",
                disclosure="LOCAL_ONLY",
                allowed_agent_ids=[ctx.requesting_agent_id],
            ),
        ),
    )
    result = TaskSupervisor(portal.memory).process(ctx, UUID(task["task_id"]))
    assert (
        result["status"] == "WAITING" and result["reason"] == "ApprovalRequiresReview"
    )


def test_skill_transfer_and_exception_requirements_are_deterministic():
    contract = HandoffSkill(
        required_prefixes=["Decision:", "Next:"],
        forbidden_phrases=["handoff prohibited"],
    )
    spec = HandoffSpec(project="Different project", sources={uuid4(): "a" * 64})
    assert (
        applicability(contract, spec, ["Decision: A different stack\nNext: Review"])[
            "decision"
        ]
        == "applicable"
    )
    assert (
        applicability(contract, spec, ["Decision: A\nNext: B\nhandoff prohibited"])[
            "decision"
        ]
        == "incompatible"
    )
    assert applicability(contract, spec, ["Decision: A"])["decision"] == "uncertain"
    assert (
        applicability(contract, spec, ["Decision: A\nNext: B"], revision_matches=False)[
            "decision"
        ]
        == "incompatible"
    )


def test_executable_contract_uses_existing_procedure_and_invalidates(portal, ctx):
    service = portal.memory
    evidence = source(portal, ctx)
    episodes = []
    # Explicit synthetic evaluation setup, not claimed as actual learning.
    # REAL episode support is exercised separately by the existing compiler tests.
    for index in range(3):
        episode = EpisodeService(service).record(
            ctx,
            EpisodeInput(
                event_id=uuid4(),
                title=f"Fixture observed handoff {index}",
                trigger="test",
                goal="handoff",
                linked_memory_ids=[evidence],
                context={
                    "goal_type": "handoff",
                    "domain": "project_management",
                    "output_format": "markdown",
                },
                outcome="success",
                attempts=[
                    ToolAttempt(
                        tool="cookieai_handoff",
                        action="cookieai_handoff",
                        intent="handoff",
                        success=True,
                    )
                ],
            ),
        )
        episodes.append(episode.episode_id)
    exp = ExperienceService(service).compile(ctx, episodes)
    proc = ProcedureService(service).compile(
        ctx, ProcedureCompile(experience_ids=[exp.experience_id])
    )
    portal.confirm_skill(
        ctx,
        proc.procedure_id,
        SkillConfirmation(
            expected_revision=1,
            explicitly_confirmed=True,
            contract=HandoffSkill(required_prefixes=["Next:"]),
        ),
    )
    body = brief(portal, ctx, [evidence], skill_id=proc.procedure_id, skill_revision=2)
    assert portal.check(ctx, body)["decision"] == "applicable"
    task = portal.submit(ctx, body)
    assert (
        TaskSupervisor(service).process(ctx, UUID(task["task_id"]))["status"]
        == "COMPLETED"
    )
    changed = brief(
        portal, ctx, [evidence], skill_id=proc.procedure_id, skill_revision=1
    )
    with pytest.raises(Conflict):
        portal.submit(ctx, changed)
    service.mutate(
        ctx,
        MutationRequest(
            operation="CORRECTION",
            target_id=evidence,
            expected_revision=1,
            candidate=MemoryCreate(
                text="Decision: Evidence withdrawn",
                disclosure="LOCAL_ONLY",
                allowed_agent_ids=[ctx.requesting_agent_id],
            ),
        ),
    )
    assert service.get(ctx, proc.procedure_id).status.value == "DISPUTED"
    replacement = source(portal, ctx, "Decision: A new project\nNext: Review")
    spec = HandoffSpec(
        project="Another project",
        sources={
            replacement: hashlib.sha256(
                service.get(ctx, replacement).text.encode()
            ).hexdigest()
        },
    )
    assert (
        portal.check_skill(ctx, proc.procedure_id, 2, spec)["decision"]
        == "incompatible"
    )


def test_local_only_blocks_all_compatible_calls_before_network(
    portal, ctx, monkeypatch
):
    service = portal.memory
    service.settings.provider_base_url = "https://example.invalid/v1"
    service.settings.embedding_provider_base_url = "https://embedding.invalid/v1"
    change_policy(
        service, ctx, DisclosureChange(mode="LOCAL_ONLY", expected_revision=0)
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("Network client was constructed")

    monkeypatch.setattr(httpx, "Client", forbidden)
    with disclosure_scope(service, ctx):
        for provider, endpoint, payload in [
            (Provider(service.settings), "/chat/completions", {"messages": []}),
            (CompatibleEmbedding(service.settings), "/embeddings", {"input": "secret"}),
        ]:
            with pytest.raises(AccessDenied):
                provider.post(endpoint, payload)
    assert policy(service, ctx)["revision"] == 1
    with pytest.raises(Conflict):
        change_policy(
            service, ctx, DisclosureChange(mode="APPROVED_CLOUD", expected_revision=0)
        )


def test_local_source_blocks_namespace_and_first_embedding(portal, ctx, monkeypatch):
    source(portal, ctx)
    assert policy(portal.memory, ctx)["local_only_sources"]
    portal.memory.settings.provider_base_url = "https://example.invalid/v1"
    with disclosure_scope(portal.memory, ctx), pytest.raises(AccessDenied):
        Provider(portal.memory.settings).post("/chat/completions", {})
    portal.memory.embedder = CompatibleEmbedding(portal.memory.settings)
    with pytest.raises(AccessDenied):
        portal.memory.create(
            ctx, MemoryCreate(text="First local-only content", disclosure="LOCAL_ONLY")
        )


def test_model_handoff_rejects_fabricated_evidence(portal, ctx, monkeypatch):
    identity = UUID(
        portal.add_source(
            ctx,
            SourceInput(
                title="Cloud-approved",
                content="Next: Review",
                disclosure="APPROVED_CLOUD",
            ),
        )["source_id"]
    )
    monkeypatch.setattr(
        Provider,
        "post",
        lambda *args: {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                key: ["fabricated:1"]
                                for key in [
                                    "summary",
                                    "decisions",
                                    "deadlines",
                                    "questions",
                                    "next_actions",
                                ]
                            }
                        )
                    }
                }
            ]
        },
    )
    task = portal.submit(
        ctx, brief(portal, ctx, [identity], mode="model", disclosure="APPROVED_CLOUD")
    )
    result = TaskSupervisor(portal.memory).process(ctx, UUID(task["task_id"]))
    assert result["verification"]["verdict"] == "FAIL"
    assert not list(workspace_for(portal.memory, ctx).glob("outputs/*.json"))


def test_handoff_http_auth_and_mobile_assets(portal, ctx):
    secret = "test-token"
    client = TestClient(
        create_app(
            service=portal.memory,
            auth=Authenticator(
                [
                    Credential(
                        hashlib.sha256(secret.encode()).hexdigest(),
                        ctx.user_id,
                        ctx.requesting_agent_id,
                        ctx.namespace_id,
                    )
                ]
            ),
        )
    )
    assert client.get("/").status_code == 200
    assert (
        "frame-ancestors 'none'" in client.get("/").headers["content-security-policy"]
    )
    assert client.get("/assets/portal.js").status_code == 200
    assert client.get("/v1/portal/sources").status_code == 401
    headers = {
        "Authorization": "Bearer " + secret,
        "X-Session-ID": str(ctx.session_id),
        "X-Purpose": "test",
    }
    result = client.post(
        "/v1/portal/sources",
        json={"title": "Note", "content": "Next: Review"},
        headers=headers,
    )
    assert result.status_code == 201, result.text
    assert len(client.get("/v1/portal/sources", headers=headers).json()) == 1


def test_paths_and_non_regular_files_are_rejected(tmp_path):
    for value in [
        "../secret.txt",
        "inputs/../../secret.txt",
        "outputs/a.txt:stream",
        "inputs/CON.txt",
        "/etc/passwd",
    ]:
        with pytest.raises(PermissionError):
            safe_path(tmp_path, value)


def test_forgetting_removes_input_and_dependent_artifact(portal, ctx):
    identity = source(portal, ctx)
    task = portal.submit(ctx, brief(portal, ctx, [identity]))
    result = TaskSupervisor(portal.memory).process(ctx, UUID(task["task_id"]))
    root = workspace_for(portal.memory, ctx)
    assert (root / f"outputs/{result['run_id']}.json").exists()
    portal.memory.delete(ctx, identity)
    assert not (root / f"inputs/{identity}.txt").exists()
    assert not (root / f"outputs/{result['run_id']}.json").exists()


def test_provider_policy_does_not_commit_failed_source_write(portal, ctx):
    from sqlalchemy import func

    from database import source_tables, tables

    portal.memory.settings.provider_base_url = "https://example.invalid/v1"
    portal.memory.embedder = CompatibleEmbedding(portal.memory.settings)
    with pytest.raises(AccessDenied):
        portal.memory.create(
            ctx,
            MemoryCreate(text="Never disclose this source", disclosure="LOCAL_ONLY"),
        )
    with portal.memory.engine.connect() as db:
        assert (
            db.execute(select(func.count()).select_from(tables.memories)).scalar_one()
            == 0
        )
        assert (
            db.execute(
                select(func.count()).select_from(source_tables.sources)
            ).scalar_one()
            == 0
        )


def test_model_handoff_actual_http_contract_usage_and_metering(
    portal, ctx, monkeypatch
):
    source_id = UUID(
        portal.add_source(
            ctx,
            SourceInput(
                title="Cloud-approved fixture",
                content="Decision: Use PostgreSQL.\nNext: Review.",
                disclosure="APPROVED_CLOUD",
            ),
        )["source_id"]
    )
    original = httpx.Client
    requests = []

    def respond(request):
        requests.append(request)
        payload = json.loads(request.content)
        lines = json.loads(payload["messages"][1]["content"])
        sections = {
            key: []
            for key in [
                "summary",
                "decisions",
                "deadlines",
                "questions",
                "next_actions",
            ]
        }
        sections["decisions"] = [lines[0]["ref"]]
        sections["next_actions"] = [lines[1]["ref"]]
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": json.dumps(sections)}}],
                "usage": {"prompt_tokens": 80, "completion_tokens": 20},
            },
        )

    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: original(transport=httpx.MockTransport(respond), **kwargs),
    )
    portal.memory.settings.provider_base_url = "https://api.tokenfactory.nebius.com/v1"
    task = portal.submit(
        ctx, brief(portal, ctx, [source_id], mode="model", disclosure="APPROVED_CLOUD")
    )
    result = TaskSupervisor(portal.memory).process(ctx, UUID(task["task_id"]))
    assert result["status"] == "COMPLETED"
    artifact = portal.artifact(ctx, UUID(task["task_id"]), UUID(result["run_id"]))
    assert artifact["usage"]["prompt_tokens"] == 80
    assert artifact["disclosure"]["sent"]
    assert len(requests) == 1 and requests[0].url.path == "/v1/chat/completions"
    with portal.memory.engine.connect() as db:
        assert db.execute(select(a.usage.c.model_calls)).scalar_one() == 1


def test_recreate_services_and_worker_preserves_task_and_receipt(portal, ctx):
    from memory.service import MemoryService
    from workers.runtime import Worker

    identity = source(portal, ctx)
    task = portal.submit(ctx, brief(portal, ctx, [identity]))
    memory = portal.memory
    restarted = MemoryService(
        memory.engine, memory.embedder, memory.extractor, memory.settings
    )
    supervisor = TaskSupervisor(restarted)
    supervisor.tick(ctx)
    worker = Worker(restarted, ctx)
    for _ in range(20):
        worker.run_once()
        state = supervisor.get(ctx, UUID(task["task_id"]))
        if state["status"] == "COMPLETED":
            break
    assert state["status"] == "COMPLETED"
    assert state["runs"][0]["payload"]["verification"]["verdict"] == "PASS"


def test_nebius_discovery_filters_model_ids_and_no_redirect_credentials():
    from scripts.nebius_preflight import discover

    def respond(request):
        assert request.url.path == "/v1/models"
        return httpx.Response(
            200, json={"data": [{"id": "nvidia/test-fixture"}, {"id": "other/model"}]}
        )

    assert discover(
        "https://api.tokenfactory.nebius.com/v1",
        "synthetic-token",
        transport=httpx.MockTransport(respond),
    ) == ["nvidia/test-fixture"]
    with pytest.raises(ValueError):
        discover("http://untrusted.invalid/v1", "synthetic-token")


def test_provider_preflight_outage_is_waiting_not_running(portal, ctx, monkeypatch):
    from memory.context.transfer import ContextTransferService

    identity = source(portal, ctx)
    task = portal.submit(ctx, brief(portal, ctx, [identity]))

    def unavailable(*args, **kwargs):
        raise httpx.ConnectError("Synthetic provider outage")

    monkeypatch.setattr(ContextTransferService, "build", unavailable)
    supervisor = TaskSupervisor(portal.memory)
    result = supervisor.process(ctx, UUID(task["task_id"]))
    assert result["status"] == "WAITING"
    state = supervisor.get(ctx, UUID(task["task_id"]))
    assert state["next_run_at"] is not None and state["runs"] == []


def test_possible_written_effect_is_uncertain_and_not_replayed(
    portal, ctx, monkeypatch
):
    identity = source(portal, ctx)
    task = portal.submit(ctx, brief(portal, ctx, [identity]))

    def interrupted(*args, **kwargs):
        raise Conflict("Synthetic interruption after artifact publication")

    monkeypatch.setattr(TaskSupervisor, "_finish", interrupted)
    supervisor = TaskSupervisor(portal.memory)
    result = supervisor.process(ctx, UUID(task["task_id"]))
    assert result["status"] == "UNCERTAIN"
    outputs = list(workspace_for(portal.memory, ctx).glob("outputs/*.json"))
    assert len(outputs) == 1
    assert supervisor.process(ctx, UUID(task["task_id"]))["status"] == "UNCERTAIN"
    assert list(workspace_for(portal.memory, ctx).glob("outputs/*.json")) == outputs


def test_handoff_prompt_budget_is_checked_before_meter_or_network(portal, ctx):
    from memory.autonomy.handoff import execute_handoff
    from memory.context.budget import ContextBudgetExceeded

    identity = UUID(
        portal.add_source(
            ctx,
            SourceInput(
                title="Large fixture",
                content="Decision: " + "x" * 5000,
                disclosure="APPROVED_CLOUD",
            ),
        )["source_id"]
    )
    spec = HandoffSpec(
        project="Budget test",
        sources={
            identity: hashlib.sha256(
                portal.memory.get(ctx, identity).text.encode()
            ).hexdigest()
        },
        mode="model",
        disclosure="APPROVED_CLOUD",
    )
    portal.memory.settings.assistant_prompt_tokens = 4096
    metered = []
    with pytest.raises(ContextBudgetExceeded):
        execute_handoff(
            portal.memory, ctx, spec, uuid4(), guard=lambda: None, meter=metered.append
        )
    assert metered == []
