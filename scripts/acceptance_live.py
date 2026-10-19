"""Seed labeled synthetic events and observe the real persistent worker, not a model double."""

import json
import os
import time
from pathlib import Path
from uuid import uuid4

import httpx
from dotenv import dotenv_values


def main():
    env = dotenv_values(".env")
    run_id = uuid4().hex[:8]
    headers = {
        "Authorization": "Bearer " + env["MEMORY_LOCAL_TEST_TOKEN"],
        "X-Session-ID": str(uuid4()),
        "X-Purpose": "Labeled synthetic worker acceptance",
    }
    report = {
        "kind": "synthetic acceptance using real embedding and reasoning models",
        "run_id": run_id,
    }
    with httpx.Client(
        base_url="http://127.0.0.1:" + env.get("MEMORY_API_PORT", "8000"),
        headers=headers,
        timeout=240,
    ) as client:

        def post(path, data):
            result = client.post(path, json=data)
            result.raise_for_status()
            return result.json()

        print("Semantic paraphrase evaluation", flush=True)
        corpus = [
            (
                "The customer avoids meals containing meat and fish.",
                "What dietary restrictions should catering accommodate?",
            ),
            (
                "The production server certificate expired and renewing it restored encrypted connections.",
                "How was the secure transport outage resolved?",
            ),
            (
                "The engineer favors a quiet room when concentrating on difficult work.",
                "Which workspace helps with demanding mental tasks?",
            ),
            (
                "The mobile application must function while disconnected from the internet.",
                "Does the phone software require network access?",
            ),
            (
                "The travel budget is capped at five hundred dollars.",
                "What is the maximum spending allowance for the trip?",
            ),
            (
                "The nightly backup is copied to a separate machine for disaster recovery.",
                "How can records be recovered if the main computer fails?",
            ),
        ]
        records = []
        for index, (fact, query) in enumerate(corpus):
            record = post(
                "/v1/memory", {"text": fact, "tags": ["synthetic-semantic-evaluation"]}
            )
            records.append((record["memory_id"], query))
        ranks = []
        for expected, query in records:
            client.headers["X-Session-ID"] = str(uuid4())
            hits = post(
                "/v1/memory/search", {"query": query, "top_k": 5, "score_threshold": 0}
            )
            rank = next(
                (
                    index + 1
                    for index, hit in enumerate(hits)
                    if hit["memory"]["memory_id"] == expected
                ),
                None,
            )
            ranks.append(rank)
        report["semantic"] = {
            "queries": len(ranks),
            "ranks": ranks,
            "recall_at_5": sum(rank is not None for rank in ranks) / len(ranks),
            "mrr_at_5": sum(1 / rank if rank else 0 for rank in ranks) / len(ranks),
        }
        print(json.dumps(report["semantic"]), flush=True)

        tool = (
            os.environ.get("MEMORY_ACCEPTANCE_RESUME_TOOL")
            or "SyntheticProbe-" + run_id
        )
        episode_ids = []
        print(
            "Seeding 24 independent synthetic episodes: 20 failures, 4 successful counterexamples",
            flush=True,
        )
        for index in range(
            0 if os.environ.get("MEMORY_ACCEPTANCE_RESUME_TOOL") else 24
        ):
            client.headers["X-Session-ID"] = str(uuid4())
            episode = post(
                "/v1/episodes",
                {
                    "title": f"Synthetic acceptance {run_id} event {index}",
                    "trigger": "explicit synthetic evaluation",
                    "goal": "evaluate a recorded probe",
                    "context": {
                        "domain": "synthetic acceptance",
                        "workflow_stage": "probe",
                    },
                    "attempts": [
                        {
                            "tool": tool,
                            "intent": "synthetic probe",
                            "action": "probe",
                            "parameters": {"configuration": "limited-timeout"},
                            "success": index >= 20,
                            "result": "synthetic observation",
                        }
                    ],
                    "outcome": "failure" if index < 20 else "success",
                },
            )
            episode_ids.append(episode["episode_id"])
            if index % 6 == 5:
                print("Episodes stored:", index + 1, flush=True)
        report["episode_ids"] = episode_ids
        print(
            "Waiting for the event-driven background worker to store and review the association",
            flush=True,
        )
        deadline = time.monotonic() + 360
        finding = None
        while time.monotonic() < deadline:
            response = client.get("/v1/insights", params={"include_candidates": True})
            response.raise_for_status()
            matches = [item for item in response.json() if tool in item["statement"]]
            if matches:
                finding = matches[0]
                if (
                    finding["support_count"] == 20
                    and finding["counterexample_count"] == 4
                ):
                    break
            time.sleep(2)
        assert finding and finding["support_count"] == 20, (
            "Worker did not process all supporting events"
        )
        assert finding["counterexample_count"] == 4
        assert finding["model_review"], "The actual model review was not exercised"
        report["finding"] = finding
        report["episode_ids"] = (
            finding["supporting_episode_ids"] + finding["counterexample_episode_ids"]
        )
        client.headers["X-Session-ID"] = str(uuid4())
        hits = post(
            "/v1/memory/search",
            {
                "query": tool + " limited timeout failure",
                "score_threshold": 0,
                "top_k": 30,
            },
        )
        report["finding_retrieved"] = any(
            hit["memory"]["memory_id"] == finding["insight_id"] for hit in hits
        )
        context = post(
            "/v1/context/build",
            {"query": tool + " limited timeout failure", "token_budget": 32000},
        )
        report["finding_in_context"] = finding["insight_id"] in json.dumps(context)
        reminder = post(
            "/v1/prospective",
            {
                "trigger_type": "CONTEXT",
                "trigger": {"value": tool},
                "action_or_memory": "Review the synthetic timeout association before another probe: "
                + run_id,
            },
        )
        triggered = post("/v1/prospective/activate", {"context": tool})
        assert any(
            item["prospective_id"] == reminder["prospective_id"] for item in triggered
        )
        assert post("/v1/prospective/activate", {"context": tool}) == []
        report["prospective_trigger"] = "passed, with repeat suppression"
        denied = httpx.get(
            str(client.base_url).rstrip("/") + "/v1/insights",
            headers={
                "Authorization": "Bearer invalid",
                "X-Session-ID": str(uuid4()),
                "X-Purpose": "denial test",
            },
        )
        assert denied.status_code == 401
        report["unauthenticated_denial"] = denied.status_code
    Path("docs/live-acceptance-results.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "status": "passed",
                "finding_status": finding["status"],
                "retrieved": report["finding_retrieved"],
                "in_context": report["finding_in_context"],
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
