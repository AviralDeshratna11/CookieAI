"""Persistent local chat backed by budgeted Token Factory inference and embeddings.

Starts no model calls until a user submits a message. Requires the existing shared
billing ledger; never creates a fresh allowance or changes production storage.
"""

import argparse
import hashlib
import logging
import os
import secrets
import threading
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import uvicorn

from apps.api.main import create_app
from database.engine import create_test_schema, make_engine
from memory.schemas import RequestContext
from memory.security.auth import Authenticator, Credential
from memory.service import MemoryService
from scripts._benchmark_common import provision
from scripts._benchmark_runtime import (
    Ledger,
    MeteredProvider,
    atomic_json,
    digest,
    isolated_settings,
)
from scripts._experiment_store import exclusive_path
from scripts._longmemeval_harness import CachedEmbedding, NoExtractor
from scripts.experiment_pipeline import ledger_snapshot, load
from workers.runtime import Worker

ROOT = Path(__file__).resolve().parents[1]
log = logging.getLogger("chat.workspace")


def open_budget(path, allowance="0.25"):
    path = Path(path).resolve()
    if not path.is_file():
        raise ValueError(
            "Supply the existing authoritative ledger; creating a fresh allowance is prohibited"
        )
    current = ledger_snapshot(path.parent)
    # ledger_snapshot expects the canonical filename; refuse ambiguous copies.
    if path.name != "budget.sqlite3":
        raise ValueError("Use the canonical budget.sqlite3 ledger")
    additional = Decimal(allowance)
    if not additional.is_finite() or not Decimal("0") < additional <= Decimal("0.25"):
        raise ValueError("Local chat allowance must be positive and at most USD0.25")
    ceiling = min(
        Decimal(current["cap_usd"]),
        Decimal(current["spent_or_reserved_usd"]) + additional,
    )
    return Ledger(path, str(ceiling), current["call_cap"]), str(ceiling)


def build_workspace(root, ledger, profile, providers=None):
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    identity_path = root / "identity.json"
    fresh = not identity_path.exists()
    identity = (
        load(identity_path)
        if not fresh
        else {
            name: str(uuid4())
            for name in ["user_id", "agent_id", "namespace_id", "session_id"]
        }
    )
    embedding_identity = digest(profile["embedding"])
    if not fresh and identity.get("embedding_identity") != embedding_identity:
        raise ValueError(
            "Workspace embedding identity changed; deliberate reindexing is required"
        )
    identity["embedding_identity"] = embedding_identity
    ctx = RequestContext(
        user_id=UUID(identity["user_id"]),
        requesting_agent_id=UUID(identity["agent_id"]),
        namespace_id=UUID(identity["namespace_id"]),
        session_id=UUID(identity["session_id"]),
        purpose="Private local Token Factory chat workspace",
        requested_scope="write",
    )
    if providers is None:
        providers = {
            "answer": MeteredProvider(
                profile["answer"], ledger, root / "cache", "answer"
            ),
            "embedding": MeteredProvider(
                profile["embedding"]["route"], ledger, root / "cache", "embedding"
            ),
        }
        providers["embedding"].cache_identity = profile["embedding"]
    embedding = profile["embedding"]
    settings = isolated_settings(
        database_url="sqlite:///" + (root / "memory.sqlite3").as_posix(),
        embedding_backend="compatible",
        embedding_dimensions=embedding["dimensions"],
        embedding_model=embedding["route"]["model"],
        embedding_version=embedding.get("version", "1"),
        embedding_document_prefix=embedding.get("document_prefix", ""),
        embedding_query_prefix=embedding.get("query_prefix", ""),
        embedding_input_type_mode=embedding.get("input_type_mode", "prefix"),
        assistant_model=profile["answer"]["model"],
        assistant_provider_base_url=profile["answer"]["base_url"],
        assistant_completion_limit_parameter="max_completion_tokens",
        assistant_reasoning_effort=profile["answer"].get("reasoning_effort"),
        assistant_output_tokens=512,
        cloud_disclosure_enabled=True,
        extraction_model="disabled-raw-ingestion-only",
        provider_base_url="http://127.0.0.1:1/v1",
    )
    engine = make_engine(settings.database_url)
    create_test_schema(engine)
    if fresh:
        provision(engine, ctx)
        atomic_json(identity_path, identity)
    memory = MemoryService(
        engine,
        CachedEmbedding(settings, providers["embedding"]),
        NoExtractor(),
        settings,
        assistant_generator=providers["answer"],
    )
    token_path = root / "access-token.txt"
    if not token_path.exists():
        token_path.write_text(secrets.token_urlsafe(32), encoding="utf-8")
        token_path.chmod(0o600)
    token = token_path.read_text(encoding="utf-8").strip()
    auth = Authenticator(
        [
            Credential(
                hashlib.sha256(token.encode()).hexdigest(),
                ctx.user_id,
                ctx.requesting_agent_id,
                ctx.namespace_id,
            )
        ]
    )
    app = create_app(settings=settings, service=memory, auth=auth)
    app.state.chat_budget = ledger
    app.state.chat_mode = "live-token-factory"
    return app, memory, ctx


def workspace_budget(root, path, allowance):
    binding_path = Path(root) / "budget-envelope.json"
    if binding_path.exists():
        binding = load(binding_path)
        if binding["ledger"] != str(Path(path).resolve()) or Decimal(
            binding["allowance"]
        ) != Decimal(allowance):
            raise ValueError(
                "Workspace budget binding changed; explicit reconciliation is required"
            )
        current = ledger_snapshot(Path(path).resolve().parent)
        return Ledger(path, binding["ceiling"], current["call_cap"]), binding["ceiling"]
    ledger, ceiling = open_budget(path, allowance)
    atomic_json(
        binding_path,
        {
            "ledger": str(Path(path).resolve()),
            "allowance": allowance,
            "ceiling": ceiling,
        },
    )
    return ledger, ceiling


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="config/benchmark.nebius.full-s.json")
    parser.add_argument("--billing-ledger", required=True)
    parser.add_argument("--max-additional-cost-usd", default="0.25")
    parser.add_argument("--key-file", default=".env.nebius")
    parser.add_argument("--workspace", default=".chat-workspace")
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    os.chdir(ROOT)
    from dotenv import dotenv_values

    key = os.environ.get("NEBIUS_API_KEY") or dotenv_values(args.key_file).get(
        "NEBIUS_API_KEY"
    )
    if not key:
        raise ValueError("Private NEBIUS_API_KEY is unavailable")
    os.environ["NEBIUS_API_KEY"] = key
    profile = load(args.profile)
    root = Path(args.workspace).resolve()
    with exclusive_path(root / "server.lock"):
        ledger, ceiling = workspace_budget(
            root, args.billing_ledger, args.max_additional_cost_usd
        )
        app, memory, ctx = build_workspace(root, ledger, profile)
        stop = threading.Event()

        def work():
            worker = Worker(memory, ctx)
            while not stop.wait(0.5):
                try:
                    worker.run_once()
                except Exception as error:
                    log.warning("Chat worker error: %s", type(error).__name__)

        thread = threading.Thread(target=work, daemon=True)
        thread.start()
        atomic_json(
            root / "runtime.json",
            {
                "pid": os.getpid(),
                "url": f"http://127.0.0.1:{args.port}",
                "model": profile["answer"]["model"],
                "embedding": embedding_model(profile),
                "local_cumulative_ceiling_usd": ceiling,
                "parent_cap_usd": ledger.summary()["cap_usd"],
                "workspace_token_file": str(root / "access-token.txt"),
                "new_allowance_usd": args.max_additional_cost_usd,
            },
        )
        print(
            f"Live local chat: http://127.0.0.1:{args.port}; private workspace token is in {root / 'access-token.txt'}",
            flush=True,
        )
        try:
            uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
        finally:
            stop.set()
            thread.join(timeout=5)
            memory.engine.dispose()


def embedding_model(profile):
    return profile["embedding"]["route"]["model"]


if __name__ == "__main__":
    main()
