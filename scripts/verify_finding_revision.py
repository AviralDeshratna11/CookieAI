"""Add counterevidence only to the labeled synthetic acceptance pattern."""

import json
import re
import time
from pathlib import Path
from uuid import uuid4

import httpx
from dotenv import dotenv_values


def main():
    report = json.loads(
        Path("docs/live-acceptance-results.json").read_text(encoding="utf-8")
    )
    before = report["finding"]
    tool = re.search(r'"tool":"(SyntheticProbe-[a-f0-9]+)"', before["statement"])[1]
    env = dotenv_values(".env")
    headers = {
        "Authorization": "Bearer " + env["MEMORY_LOCAL_TEST_TOKEN"],
        "X-Session-ID": str(uuid4()),
        "X-Purpose": "Synthetic counterevidence revision verification",
    }
    with httpx.Client(
        base_url="http://127.0.0.1:" + env.get("MEMORY_API_PORT", "8000"),
        headers=headers,
        timeout=240,
    ) as client:
        current = client.get("/v1/insights", params={"include_candidates": True})
        current.raise_for_status()
        before = next(
            item
            for item in current.json()
            if item["insight_id"] == before["insight_id"]
        )
        response = client.post(
            "/v1/episodes",
            json={
                "event_id": str(uuid4()),
                "title": "Synthetic successful counterexample for " + tool,
                "trigger": "synthetic acceptance follow-up",
                "goal": "test confidence revision",
                "outcome": "success",
                "attempts": [
                    {
                        "tool": tool,
                        "intent": "synthetic probe",
                        "action": "probe",
                        "parameters": {"configuration": "limited-timeout"},
                        "success": True,
                        "result": "synthetic successful observation",
                    }
                ],
            },
        )
        response.raise_for_status()
        print(
            "New synthetic counterexample recorded; waiting for worker revision",
            flush=True,
        )
        deadline = time.monotonic() + 360
        after = None
        while time.monotonic() < deadline:
            response = client.get("/v1/insights", params={"include_candidates": True})
            response.raise_for_status()
            after = next(
                (
                    item
                    for item in response.json()
                    if item["insight_id"] == before["insight_id"]
                ),
                None,
            )
            if after and after["counterexample_count"] > before["counterexample_count"]:
                break
            time.sleep(2)
        assert (
            after
            and after["counterexample_count"] == before["counterexample_count"] + 1
        )
        assert after["truth_confidence"] < before["truth_confidence"]
        response = client.get("/v1/prospective")
        response.raise_for_status()
        opportunities = [
            item
            for item in response.json()
            if item.get("origin") == "INFERRED_OPPORTUNITY"
            and before["insight_id"] in item.get("provenance_ids", [])
        ]
        if after["status"] == "ACTIVE":
            assert opportunities, (
                "Accepted revised finding did not create a future opportunity"
            )
        result = {
            "kind": "live synthetic counterevidence through actual persistent worker",
            "finding_id": before["insight_id"],
            "confidence_before": before["truth_confidence"],
            "confidence_after": after["truth_confidence"],
            "counterexamples_before": before["counterexample_count"],
            "counterexamples_after": after["counterexample_count"],
            "status_after": after["status"],
            "inferred_opportunities": opportunities,
        }
        Path("docs/live-revision-results.json").write_text(
            json.dumps(result, indent=2), encoding="utf-8"
        )
        print(
            json.dumps(
                {
                    "confidence_before": result["confidence_before"],
                    "confidence_after": result["confidence_after"],
                    "status": after["status"],
                    "opportunities": len(opportunities),
                }
            ),
            flush=True,
        )


if __name__ == "__main__":
    main()
