"""Bounded real-provider smoke comparison using only synthetic workspace data."""

import argparse
import json
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from uuid import uuid4

from memory.agent.hermes import HermesBackend
from memory.agent.service import AgentService, TurnInput
from memory.config import Settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument(
        "--output", type=Path, default=Path("docs/hermes-live-results.json")
    )
    args = parser.parse_args()
    # Loading configured credentials does not connect to or mutate the database.
    settings = Settings(
        _env_file=(".env", ".env.supabase", ".env.cloud"),
        hermes_python=args.python,
        hermes_source=args.source,
        assistant_output_tokens=512,
        hermes_max_iterations=5,
        hermes_timeout_seconds=180,
        request_timeout_seconds=60,
    )
    message = (
        "Synthetic acceptance task: read quote.txt from the approved tool workspace. "
        "Calculate units times unit_cost using cookieai_calculate. State the total. "
        "If you cannot access the file, say so rather than inventing its contents."
    )
    context = {"trust": "untrusted data", "memories": []}
    report = {
        "synthetic": True,
        "scope": "One live smoke scenario; not representative quality evidence",
        "model": settings.extraction_model,
    }
    start = time.monotonic()
    try:
        baseline = AgentService(SimpleNamespace(settings=settings)).generate(
            TurnInput(message=message, idempotency_key=uuid4().hex), context
        )
        report["assistant"] = {
            "latency_ms": (time.monotonic() - start) * 1000,
            "answer": baseline,
            "can_access_fixture": False,
        }
    except Exception as failure:
        report["assistant"] = {"failure_class": type(failure).__name__}
    with TemporaryDirectory(prefix="cookieai-synthetic-fixture-") as directory:
        Path(directory, "quote.txt").write_text(
            "units=13\nunit_cost=7.25\n", encoding="utf-8"
        )
        try:
            result = HermesBackend(settings, workspace=directory).run(
                uuid4(), message, context
            )
            report["hermes"] = result.model_dump(mode="json")
            report["scenario_passed"] = (
                result.status == "COMPLETED"
                and "94.25" in result.answer
                and all(
                    any(
                        item["tool"] == tool and item["success"]
                        for item in result.observations
                    )
                    for tool in ("cookieai_read_text", "cookieai_calculate")
                )
            )
        except Exception as failure:
            report["hermes"] = {"failure_class": type(failure).__name__}
            report["scenario_passed"] = False
    report["recommendation"] = (
        "Keep opt-in; representative benefit and operations evaluation remains required"
    )
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {"report": str(args.output), "scenario_passed": report["scenario_passed"]}
        )
    )


if __name__ == "__main__":
    main()
