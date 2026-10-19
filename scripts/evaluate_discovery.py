"""Real worker/model evaluation of recurring source choices; events are synthetic."""

import json
import time
from pathlib import Path
from uuid import uuid4

import httpx
from dotenv import dotenv_values


def main():
    env = dotenv_values(".env")
    marker = "SyntheticLodging-" + uuid4().hex[:8]
    headers = {
        "Authorization": "Bearer " + env["MEMORY_LOCAL_TEST_TOKEN"],
        "X-Session-ID": str(uuid4()),
        "X-Purpose": "Explicitly synthetic discovery evaluation",
    }
    variants = [
        "selected a quiet room away from the main road",
        "chose accommodation with little street noise",
        "preferred a peaceful hotel room rather than noisy roadside lodging",
        "picked a room facing the courtyard to avoid traffic sounds",
    ]
    ids = []
    with httpx.Client(
        base_url="http://127.0.0.1:" + env.get("MEMORY_API_PORT", "8000"),
        headers=headers,
        timeout=240,
    ) as client:
        for index in range(12):
            client.headers["X-Session-ID"] = str(uuid4())
            response = client.post(
                "/v1/memory",
                json={
                    "text": f"Synthetic observation {marker} case {index}: the test traveler {variants[index % len(variants)]}.",
                    "type": "OBSERVATION",
                    "entities": [marker],
                    "tags": ["synthetic-evaluation"],
                },
            )
            response.raise_for_status()
            ids.append(response.json()["memory_id"])
        response = client.post("/v1/reflection/run", params={"background": True})
        response.raise_for_status()
        job = response.json()["job_id"]
        print("Queued general-discovery evaluation:", job, flush=True)
        deadline = time.monotonic() + 360
        while time.monotonic() < deadline:
            jobs = client.get("/v1/jobs", params={"limit": 200})
            jobs.raise_for_status()
            current = next(item for item in jobs.json() if item["id"] == job)
            if current["status"] in {"DONE", "FAILED"}:
                break
            time.sleep(2)
        assert current["status"] == "DONE", current
        response = client.get("/v1/insights", params={"include_candidates": True})
        response.raise_for_status()
        findings = [
            item
            for item in response.json()
            if set(item.get("supporting_memory_ids", [])) & set(ids)
        ]
        report = {
            "kind": "synthetic recurring-choice evaluation using real persistent worker and model calls",
            "marker": marker,
            "job_id": job,
            "source_memory_ids": ids,
            "job_status": current["status"],
            "findings": findings,
            "found_pattern": bool(findings),
        }
        Path("docs/general-discovery-results.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )
        print(
            json.dumps({"status": current["status"], "findings": len(findings)}),
            flush=True,
        )


if __name__ == "__main__":
    main()
