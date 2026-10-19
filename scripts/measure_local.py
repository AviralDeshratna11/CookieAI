"""Measure the real semantic API at its actual local dataset size."""

import asyncio
import json
from pathlib import Path
from uuid import uuid4

import httpx
from dotenv import dotenv_values

from examples.load_test import run


def main():
    env = dotenv_values(".env")
    url = "http://127.0.0.1:" + env.get("MEMORY_API_PORT", "8000")
    token = env["MEMORY_LOCAL_TEST_TOKEN"]
    credentials = json.loads(
        Path("config/credentials.json").read_text(encoding="utf-8")
    )[0]
    response = httpx.get(
        url + "/v1/user/" + credentials["user_id"] + "/memory",
        headers={
            "Authorization": "Bearer " + token,
            "X-Session-ID": str(uuid4()),
            "X-Purpose": "Local capacity measurement",
        },
    )
    response.raise_for_status()
    result = asyncio.run(run(url, token, requests=40, concurrency=4))
    result.update(
        kind="short local semantic retrieval smoke, not a sustained capacity test",
        authorized_memory_count=len(response.json()["memories"]),
        embedding_model=env["MEMORY_EMBEDDING_MODEL"],
    )
    Path("docs/live-performance-results.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )
    print(json.dumps(result))


if __name__ == "__main__":
    main()
