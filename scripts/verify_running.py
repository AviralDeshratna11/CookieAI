"""Exercise the running API using synthetic data and the local bootstrap token."""

import json
from uuid import uuid4

import httpx
from dotenv import dotenv_values


def main():
    env = dotenv_values(".env")
    headers = {
        "Authorization": "Bearer " + env["MEMORY_LOCAL_TEST_TOKEN"],
        "X-Session-ID": str(uuid4()),
        "X-Purpose": "Synthetic Nemotron integration verification",
    }
    base = "http://127.0.0.1:" + env.get("MEMORY_API_PORT", "8000")
    with httpx.Client(base_url=base, headers=headers, timeout=240) as client:
        response = client.post(
            "/v1/memory/remember",
            json={
                "messages": [
                    {
                        "role": "user",
                        "content": "Project Aurora uses PostgreSQL as its primary database.",
                    }
                ],
                "mode": "infer",
                "remember_explicitly": True,
                "idempotency_key": "nemotron-aurora-" + uuid4().hex,
            },
        )
        print("LLM extraction HTTP:", response.status_code, flush=True)
        response.raise_for_status()
        memories = response.json()
        assert memories, "Model produced no memories"
        print("Stored:", json.dumps([m["text"] for m in memories]), flush=True)
        client.headers["X-Session-ID"] = str(uuid4())
        response = client.post(
            "/v1/memory/search",
            json={"query": "Aurora PostgreSQL database", "score_threshold": 0},
        )
        response.raise_for_status()
        ids = {hit["memory"]["memory_id"] for hit in response.json()}
        assert all(m["memory_id"] in ids for m in memories)
        print("Cross-session recall: passed", flush=True)
        response = client.post(
            "/v1/context/build", json={"query": "Aurora PostgreSQL database"}
        )
        response.raise_for_status()
        assert "Aurora" in response.text
        print("Context composition: passed", flush=True)


if __name__ == "__main__":
    main()
