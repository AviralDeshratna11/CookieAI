"""Explicit local-only load driver; supply the running server and a test credential."""

import argparse
import asyncio
import json
import time
from uuid import uuid4

import httpx


async def run(url, token, requests=50, concurrency=5):
    if not url.startswith(("http://127.0.0.1:", "http://localhost:")):
        raise ValueError("load testing is restricted to an explicitly local server")
    semaphore = asyncio.Semaphore(concurrency)
    latencies = []
    statuses = []
    async with httpx.AsyncClient(
        base_url=url,
        timeout=30,
        headers={
            "Authorization": "Bearer " + token,
            "X-Session-ID": str(uuid4()),
            "X-Purpose": "local load test",
        },
    ) as client:

        async def query():
            async with semaphore:
                start = time.perf_counter()
                response = await client.post(
                    "/v1/memory/search",
                    json={"query": "Alpha database", "score_threshold": 0},
                )
                latencies.append(time.perf_counter() - start)
                statuses.append(response.status_code)

        start = time.perf_counter()
        await asyncio.gather(*(query() for _ in range(requests)))
        elapsed = time.perf_counter() - start
    return {
        "requests": requests,
        "concurrency": concurrency,
        "elapsed_seconds": elapsed,
        "requests_per_second": requests / elapsed,
        "p95_ms": sorted(latencies)[int(0.95 * (len(latencies) - 1))] * 1000,
        "errors": sum(code != 200 for code in statuses),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--token", required=True)
    args = parser.parse_args()
    print(json.dumps(asyncio.run(run(args.url, args.token)), indent=2))
