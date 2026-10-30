import threading
from pathlib import Path

import pytest

from scripts._benchmark_runtime import atomic_json
from scripts._longmemeval_harness import CachedEmbedding, validate_config


def test_atomic_checkpoint_retries_local_windows_rename_only(tmp_path, monkeypatch):
    original = Path.replace
    calls = []

    def replace(path, target):
        calls.append(path)
        if len(calls) < 3:
            raise PermissionError("sharing violation")
        return original(path, target)

    monkeypatch.setattr(Path, "replace", replace)
    monkeypatch.setattr("scripts._benchmark_runtime.time.sleep", lambda _: None)
    atomic_json(tmp_path / "state.json", {"saved": True})
    assert len(calls) == 3
    assert (tmp_path / "state.json").read_text().strip()
    assert not list(tmp_path.glob("*.tmp"))


def test_parallel_embedding_waves_bounded_and_failure_does_not_submit_next_wave():
    embedding = object.__new__(CachedEmbedding)
    embedding.precomputed = {}
    barrier = threading.Barrier(4)
    called = []
    lock = threading.Lock()

    def embed_many(batch):
        with lock:
            called.append(batch)
        barrier.wait(timeout=5)
        if "source0" in batch[0]:
            raise ValueError("fixture error")
        return [[float(len(text))] for text in batch]

    embedding.embed_many = embed_many
    rows = [
        {"source_id": f"source{i}", "role": "user", "text": "plain text"}
        for i in range(12)
    ]
    with pytest.raises(ValueError, match="fixture error"):
        embedding.prewarm(rows, 1, 4)
    assert len(called) == 4
    assert len(embedding.precomputed) == 3
    with pytest.raises(ValueError, match="ingestion_workers"):
        validate_config({"ingestion_workers": 5})


def test_parallel_embedding_preserves_source_vector_order():
    embedding = object.__new__(CachedEmbedding)
    embedding.precomputed = {}
    embedding.embed_many = lambda batch: [[text] for text in batch]
    rows = [
        {"source_id": str(i), "role": "user", "text": "plain text"} for i in range(9)
    ]
    embedding.prewarm(rows, 2, 4)
    assert len(embedding.precomputed) == 9
    assert all(value == [text] for text, value in embedding.precomputed.items())


def test_cloud_requires_transferred_exact_route_proof_before_preparation(tmp_path):
    from scripts._benchmark_runtime import digest
    from scripts.benchmark_cloud_runner import validate_tool_proof

    profile = {"answer": {"model": "nvidia/fixture", "reasoning_effort": "none"}}
    with pytest.raises(ValueError, match="Transfer the existing"):
        validate_tool_proof(profile, tmp_path)
    proof = tmp_path / "cache" / (digest(profile["answer"]) + ".tools.json")
    atomic_json(proof, {"verified": True})
    assert validate_tool_proof(profile, tmp_path) == proof
    with pytest.raises(ValueError):
        validate_tool_proof({"answer": {"model": "nvidia/different"}}, tmp_path)


def test_hermes_backend_reuses_authorized_index_without_reingestion(
    tmp_path, monkeypatch
):
    import json

    from scripts._benchmark_runtime import isolated_settings
    from scripts._experiment_store import instance_store
    from scripts._longmemeval_harness import ROOT, execute_in_instance, source_rows

    instance = json.loads(
        (ROOT / "tests/fixtures/longmemeval_synthetic.json").read_text(encoding="utf-8")
    )[0]
    settings = isolated_settings(
        database_url="sqlite://", cloud_disclosure_enabled=False
    )
    with instance_store(instance, settings, {}, {}, tmp_path) as (
        _,
        ctx,
        mapping,
        _,
        trace,
    ):
        namespace = ctx.namespace_id
        assert trace["sources_created"] > 0
        ids = set(mapping)

    def unexpected_ingestion(*args):
        pytest.fail("Hermes rebuilt a completed corpus")

    def scripted(*args, tool_extension, **kwargs):
        assert tool_extension.ctx.namespace_id == namespace
        assert set(tool_extension.mapping) == ids
        tool_extension.guard()
        return "fixture answer", {"status": "COMPLETED"}

    monkeypatch.setattr("scripts._longmemeval_harness.ingest", unexpected_ingestion)
    monkeypatch.setattr("scripts._longmemeval_harness.run_hermes", scripted)
    answer, result = execute_in_instance(
        instance,
        settings,
        {"answer": object()},
        {},
        source_rows(instance),
        artifact_root=tmp_path,
    )
    assert answer == "fixture answer"
    assert result["status"] == "COMPLETED"


def test_parallel_partitions_preserve_all_questions_once_and_reject_mutation():
    import copy
    import json

    from scripts._longmemeval_harness import ROOT
    from scripts.benchmark_parallel_runner import partition, validate_partition

    sample = json.loads(
        (ROOT / "tests/fixtures/longmemeval_synthetic.json").read_text(encoding="utf-8")
    )[0]
    rows = []
    for index in range(500):
        row = copy.deepcopy(sample)
        row["question_id"] = f"fixture-{index:03d}"
        rows.append(row)
    groups = partition(rows)
    assert [len(group) for group in groups] == [125] * 4
    assert len({row["question_id"] for group in groups for row in group}) == 500
    changed = copy.deepcopy(groups)
    changed[0][0]["question"] = "Mutated question"
    with pytest.raises(ValueError, match="preserve every"):
        validate_partition(rows, changed)
    changed = copy.deepcopy(groups)
    changed[0].append(changed[1].pop())
    validate_partition(rows, changed)
    changed[0].append(changed[0][0])
    with pytest.raises(ValueError, match="exactly once"):
        validate_partition(rows, changed)


def test_parallel_collect_denies_cross_partition_and_duplicate_outcomes(
    tmp_path, monkeypatch
):
    import scripts.benchmark_parallel_runner as runner

    monkeypatch.setattr(runner, "BASE", tmp_path)
    manifest = {
        "partitions": [["q0"], ["q1"], ["q2"], ["q3"]],
        "modes": ["direct", "hermes"],
    }
    path = tmp_path / "worker-0/run/report.json"
    atomic_json(
        path,
        {
            "questions_detail": [
                {"question_id": "q0", "mode": "direct", "status": "graded"}
            ]
        },
    )
    records, workers = runner.collect(manifest)
    assert len(records) == 1 and workers[0]["graded"] == 1
    atomic_json(path, {"questions_detail": records * 2})
    with pytest.raises(ValueError, match="Duplicate"):
        runner.collect(manifest)
    atomic_json(
        path,
        {
            "questions_detail": [
                {"question_id": "q1", "mode": "direct", "status": "graded"}
            ]
        },
    )
    with pytest.raises(ValueError, match="frozen partition"):
        runner.collect(manifest)
