"""Exclusive run/index ownership and resumable disposable SQLite projections."""

import json
import os
import re
import shutil
from contextlib import contextmanager
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

from database.engine import create_test_schema, make_engine
from memory.schemas import RequestContext
from memory.service import MemoryService
from models.providers import HashEmbedding
from scripts._benchmark_common import provision
from scripts._benchmark_runtime import atomic_json, digest


def release_scratch(artifact_root, *, index_fingerprint=None, embedding_key=None):
    """Delete only named generated scratch children; never reports or the ledger."""
    root = Path(artifact_root).absolute()
    if root.resolve() != root:
        raise ValueError("Artifact root must not traverse links")
    for parent, key in (
        (root / "indexes", index_fingerprint),
        (root / "cache" / "embedding-instances", embedding_key),
    ):
        if key is None:
            continue
        if not re.fullmatch(r"[0-9a-f]{64}", key):
            raise ValueError("Scratch identity must be an exact SHA256")
        target = parent / key
        # Validate absolute containment and every component before recursion.
        if (
            target.resolve().parent != parent.resolve()
            or not target.resolve().is_relative_to(root.resolve())
        ):
            raise ValueError("Scratch path escapes artifact root")
        current = root
        for part in target.relative_to(root).parts:
            current = current / part
            if current.is_symlink() or (
                current.exists() and current.resolve() != current
            ):
                raise ValueError("Linked scratch path is not eligible for cleanup")
        if (target / "owner.lock").exists():
            raise ValueError("Cannot release a claimed scratch index")
        if target.exists():
            shutil.rmtree(target)


@contextmanager
def exclusive_path(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        handle = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise RuntimeError(
            "Artifact is already claimed; inspect stale owner before recovery"
        ) from None
    try:
        os.write(
            handle,
            json.dumps(
                {"pid": os.getpid(), "automatic_stale_recovery": False}
            ).encode(),
        )
        os.close(handle)
        handle = None
        yield
    finally:
        if handle is not None:
            os.close(handle)
        path.unlink(missing_ok=True)


@contextmanager
def instance_store(instance, settings, providers, config, artifact_root):
    from scripts._longmemeval_harness import (
        PREPROCESSING_VERSION,
        CachedEmbedding,
        NoExtractor,
        effective_policy,
        ingest,
        source_rows,
    )

    history = {
        key: instance[key]
        for key in ("haystack_session_ids", "haystack_dates", "haystack_sessions")
    }
    descriptor = {
        "question_id": instance["question_id"],
        "history_sha256": digest(history),
        "embedding": config.get(
            "embedding",
            {"backend": "hash-test", "dimensions": settings.embedding_dimensions},
        ),
        "policy": effective_policy(config).model_dump(mode="json"),
        "preprocessing": PREPROCESSING_VERSION,
    }
    project = Path(__file__).resolve().parents[1]
    descriptor["projection_code"] = {
        name: digest((project / name).read_bytes().hex())
        for name in (
            "memory/service.py",
            "memory/policy.py",
            "memory/retrieval/hybrid.py",
            "models/providers.py",
            "scripts/_experiment_store.py",
        )
    }
    fingerprint = digest(descriptor)
    root = Path(artifact_root) / "indexes" / fingerprint
    root.mkdir(parents=True, exist_ok=True)
    with exclusive_path(root / "owner.lock"):
        engine = make_engine(
            "sqlite:///" + (root / "index.sqlite3").resolve().as_posix()
        )
        try:
            create_test_schema(engine)
            state_path = root / "state.json"
            state = (
                json.loads(state_path.read_text(encoding="utf-8"))
                if state_path.exists()
                else None
            )
            if state and state["fingerprint"] != fingerprint:
                raise ValueError("Index manifest mismatch")
            namespace = uuid5(NAMESPACE_URL, fingerprint)
            ctx = RequestContext(
                user_id=uuid5(namespace, "user"),
                requesting_agent_id=uuid5(namespace, "agent"),
                namespace_id=namespace,
                session_id=uuid5(namespace, "session"),
                purpose="isolated versioned experiment corpus",
                requested_scope="write",
            )
            if state is None:
                from sqlalchemy import select

                from database import tables as t

                with engine.connect() as db:
                    exists = db.execute(
                        select(t.namespaces.c.id).where(t.namespaces.c.id == namespace)
                    ).first()
                if not exists:
                    provision(engine, ctx)
                state = {
                    "fingerprint": fingerprint,
                    "descriptor": descriptor,
                    "sources": {},
                    "status": "indexing",
                }
                atomic_json(state_path, state)
            embedder = (
                CachedEmbedding(settings, providers["embedding"])
                if "embedding" in providers
                else HashEmbedding(settings.embedding_dimensions)
            )
            traces = []
            service = MemoryService(
                engine,
                embedder,
                NoExtractor(),
                settings,
                policy_override=effective_policy(config),
                search_observer=traces.append,
            )
            rows = source_rows(history)
            missing = [row for row in rows if row["source_id"] not in state["sources"]]
            batch_size = config.get("embedding", {}).get("batch_size", 1)
            if isinstance(embedder, CachedEmbedding) and batch_size > 1 and missing:
                embedder.prewarm(
                    missing, batch_size, config.get("ingestion_workers", 1)
                )
            for row in missing:
                mapping = ingest(service, ctx, [row])
                memory_id = next(iter(mapping))
                state["sources"][row["source_id"]] = memory_id
                atomic_json(state_path, state)
            state["status"] = "completed"
            atomic_json(state_path, state)
            mapping = {}
            for row in rows:
                mid = state["sources"][row["source_id"]]
                memory = service.get(ctx, UUID(mid))
                if memory.namespace_id != namespace:
                    raise ValueError("Index source crossed namespace")
                mapping.setdefault(mid, []).append(row)
            yield (
                service,
                ctx,
                mapping,
                traces,
                {
                    "fingerprint": fingerprint,
                    "sources_reused": len(rows) - len(missing),
                    "sources_created": len(missing),
                    "namespace_id": str(namespace),
                },
            )
        finally:
            engine.dispose()
