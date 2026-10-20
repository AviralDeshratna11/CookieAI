"""Memory-assisted conversation through the durable API/worker loop."""

import argparse
import time
from uuid import uuid4

import httpx
from dotenv import dotenv_values


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--message")
    parser.add_argument("--session", default=str(uuid4()))
    parser.add_argument("--wait-seconds", type=int, default=300)
    parser.add_argument(
        "--backend", choices=["assistant", "hermes"], default="assistant"
    )
    args = parser.parse_args()
    env = dotenv_values(".env")
    with httpx.Client(
        base_url="http://127.0.0.1:" + env.get("MEMORY_API_PORT", "8000"),
        headers={
            "Authorization": "Bearer " + env["MEMORY_LOCAL_TEST_TOKEN"],
            "X-Session-ID": args.session,
            "X-Purpose": "Interactive memory-assisted conversation",
        },
        timeout=180,
    ) as client:
        print("Session:", args.session)
        while True:
            message = args.message or input("You: ").strip()
            if message.casefold() in {"exit", "quit"}:
                break
            response = client.post(
                "/v1/agent/turn",
                json={
                    "message": message,
                    "idempotency_key": uuid4().hex,
                    "backend": args.backend,
                },
            )
            response.raise_for_status()
            identity = response.json()["turn_id"]
            print("Turn:", identity, flush=True)
            deadline = time.monotonic() + args.wait_seconds
            while time.monotonic() < deadline:
                response = client.get("/v1/agent/turn/" + identity)
                response.raise_for_status()
                payload = response.json()
                if payload["status"] == "COMPLETED":
                    print("Assistant:", payload["answer"], flush=True)
                    break
                if payload["status"] == "CANCELLED":
                    print("This turn was canceled because its evidence was erased.")
                    break
                if payload.get("job_status") == "FAILED":
                    print(
                        "Turn needs retry:",
                        payload.get("job_id"),
                        payload.get("failure_class"),
                    )
                    break
                time.sleep(1)
            else:
                print(
                    "Still queued or retrying. Inspect /v1/jobs and retrieve this turn ID later."
                )
            if args.message:
                break


if __name__ == "__main__":
    main()
