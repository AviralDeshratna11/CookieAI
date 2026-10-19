"""Check migrated retrieval/context without creating or deleting memories."""

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import httpx
from dotenv import dotenv_values


def main():
    env = dotenv_values(".env")
    report = {"verified_at": datetime.now(timezone.utc).isoformat()}
    headers = {
        "Authorization": "Bearer " + env["MEMORY_LOCAL_TEST_TOKEN"],
        "X-Session-ID": str(uuid4()),
        "X-Purpose": "Synthetic Supabase cutover verification",
    }
    base = "http://127.0.0.1:" + env.get("MEMORY_API_PORT", "8000")
    try:
        with httpx.Client(base_url=base, headers=headers, timeout=180) as client:
            response = client.get("/health/live")
            response.raise_for_status()
            report["api_healthy"] = True
            response = client.post(
                "/v1/memory/search",
                json={"query": "Aurora PostgreSQL database", "score_threshold": 0},
            )
            response.raise_for_status()
            assert any("Aurora" in hit["memory"]["text"] for hit in response.json())
            report["migrated_memory_retrieval"] = True
            response = client.post(
                "/v1/context/build", json={"query": "Aurora PostgreSQL database"}
            )
            response.raise_for_status()
            assert "Aurora" in response.text
            report["context_composition"] = True
            for endpoint, key in [
                ("/v1/insights?include_candidates=true", "insights"),
                ("/v1/prospective", "prospective"),
                ("/v1/jobs", "jobs"),
            ]:
                response = client.get(endpoint)
                response.raise_for_status()
                report[key + "_visible"] = len(response.json())
            response = client.get(
                "/v1/jobs", headers={"Authorization": "Bearer invalid-token"}
            )
            assert response.status_code == 401
            report["invalid_token_denied"] = True
        Path("docs/supabase-read-results.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )
        print(json.dumps(report, indent=2))
    except Exception as error:
        print(
            "Live verification failed: "
            + type(error).__name__
            + "; credentials were not printed."
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
