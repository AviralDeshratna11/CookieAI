"""Real TCP HTTP -> FastAPI -> PostgreSQL -> pgvector -> deletion, not an in-process mock."""

import hashlib
import json
import os
import socket
import subprocess
import sys
import time
from uuid import uuid4

import httpx
import pytest
from test_postgres import postgres as postgres

pytestmark = pytest.mark.postgres


def test_live_server_postgres_flow(postgres, ctx, tmp_path):
    credential_file = tmp_path / "credentials.json"
    token = "temporary-live-test-token-" + uuid4().hex
    credential_file.write_text(
        json.dumps(
            [
                {
                    "token_sha256": hashlib.sha256(token.encode()).hexdigest(),
                    "user_id": str(ctx.user_id),
                    "agent_id": str(ctx.requesting_agent_id),
                    "namespace_id": str(ctx.namespace_id),
                }
            ]
        )
    )
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    environment = {
        **os.environ,
        "MEMORY_CREDENTIALS_FILE": str(credential_file),
        "MEMORY_EMBEDDING_BACKEND": "hash-test",
    }
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "apps.api.main:create_app",
            "--factory",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--no-access-log",
        ],
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=10) as client:
            deadline = time.monotonic() + 15
            while True:
                try:
                    if client.get("/health/live").status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                if process.poll() is not None or time.monotonic() > deadline:
                    pytest.fail("live API failed to start")
                time.sleep(0.05)
            headers = {
                "Authorization": "Bearer " + token,
                "X-Session-ID": str(ctx.session_id),
                "X-Purpose": "live acceptance",
            }
            created = client.post(
                "/v1/memory/remember",
                headers=headers,
                json={
                    "mode": "raw",
                    "idempotency_key": "live-turn",
                    "messages": [
                        {"role": "user", "content": "Project Alpha uses PostgreSQL"}
                    ],
                },
            )
            assert created.status_code == 200, created.text
            memory_id = created.json()[0]["memory_id"]
            headers["X-Session-ID"] = str(uuid4())
            recalled = client.post(
                "/v1/memory/search",
                headers=headers,
                json={"query": "Alpha PostgreSQL", "score_threshold": 0},
            )
            assert recalled.status_code == 200, recalled.text
            assert recalled.json()[0]["memory"]["memory_id"] == memory_id
            transferred = client.post(
                "/v1/context/build", headers=headers, json={"query": "Alpha PostgreSQL"}
            )
            assert transferred.status_code == 200
            assert "PostgreSQL" in transferred.text
            assert (
                client.delete(f"/v1/memory/{memory_id}", headers=headers).status_code
                == 204
            )
            assert (
                client.get(f"/v1/memory/{memory_id}", headers=headers).status_code
                == 404
            )
            import asyncio

            from examples.load_test import run

            report = asyncio.run(
                run(f"http://127.0.0.1:{port}", token, requests=20, concurrency=4)
            )
            assert report["errors"] == 0
            from pathlib import Path

            report_dir = Path(os.environ.get("MEMORY_TEST_REPORT_DIR", "docs"))
            report_dir.mkdir(parents=True, exist_ok=True)
            (report_dir / "load-test-results.json").write_text(
                json.dumps(report, indent=2), encoding="utf-8"
            )
    finally:
        process.terminate()
        process.wait(timeout=10)
