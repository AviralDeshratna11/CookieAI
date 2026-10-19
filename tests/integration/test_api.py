import hashlib
from uuid import uuid4

from fastapi.testclient import TestClient

from apps.api.main import create_app
from memory.security.auth import Authenticator, Credential


def test_http_contracts_auth_crud_search_openapi(service, ctx):
    token = "test-credential-only"
    auth = Authenticator(
        [
            Credential(
                hashlib.sha256(token.encode()).hexdigest(),
                ctx.user_id,
                ctx.requesting_agent_id,
                ctx.namespace_id,
            )
        ]
    )
    client = TestClient(create_app(service=service, auth=auth))
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Session-ID": str(ctx.session_id),
        "X-Purpose": "test",
    }
    assert client.post("/v1/memory/search", json={"query": "secret"}).status_code == 401
    assert (
        client.post(
            "/v1/memory",
            headers=headers,
            json={"text": "Alpha uses PostgreSQL", "owner_id": str(uuid4())},
        ).status_code
        == 422
    )
    created = client.post(
        "/v1/memory", headers=headers, json={"text": "Alpha uses PostgreSQL"}
    )
    assert created.status_code == 201, created.text
    memory_id = created.json()["memory_id"]
    assert client.get(f"/v1/memory/{memory_id}", headers=headers).status_code == 200
    hits = client.post(
        "/v1/memory/search",
        headers=headers,
        json={"query": "Alpha PostgreSQL", "score_threshold": 0},
    )
    assert hits.status_code == 200
    assert hits.json()[0]["memory"]["memory_id"] == memory_id
    updated = client.patch(
        f"/v1/memory/{memory_id}",
        headers=headers,
        json={"text": "Alpha uses PostgreSQL 17", "expected_revision": 1},
    )
    assert updated.status_code == 200
    assert (
        client.patch(
            f"/v1/memory/{memory_id}", headers=headers, json={"expected_revision": 1}
        ).status_code
        == 409
    )
    assert client.get(f"/v1/provenance/{memory_id}", headers=headers).status_code == 200
    assert client.delete(f"/v1/memory/{memory_id}", headers=headers).status_code == 204
    assert client.get(f"/v1/memory/{memory_id}", headers=headers).status_code == 404
    assert (
        "HTTPBearer"
        in client.get("/openapi.json").json()["components"]["securitySchemes"]
    )


def test_missing_credential_file_fails_closed(service):
    client = TestClient(create_app(service=service, auth=Authenticator([])))
    assert (
        client.get(
            "/v1/memory/" + str(uuid4()),
            headers={
                "Authorization": "Bearer anything",
                "X-Session-ID": str(uuid4()),
                "X-Purpose": "test",
            },
        ).status_code
        == 401
    )
