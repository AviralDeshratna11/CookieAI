"""Frozen, paired base/checkpoint report comparison; no model promotion."""

import math

from scripts._benchmark_runtime import digest
from scripts._experiment_contracts import ComparisonPlan


def wilson(correct, total):
    if not total:
        return None
    z = 1.959963984540054
    p = correct / total
    denominator = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    half = (
        z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    )
    return [max(0, center - half), min(1, center + half)]


def compare_reports(base, trained, comparison):
    comparison = ComparisonPlan.model_validate(comparison)
    for report, model in (
        (base, comparison.base_model),
        (trained, comparison.checkpoint_model),
    ):
        manifest = report["manifest"]
        if (
            manifest["dataset_sha256"] != comparison.dataset_sha256
            or manifest["question_ids"] != comparison.question_ids
            or digest(manifest["effective_retrieval_policy"])
            != comparison.effective_policy_sha256
            or manifest["prompt_sha256"] != comparison.answer_prompt_sha256
            or manifest["response_adapter"] != comparison.response_adapter
            or digest(manifest["config"]["judge"]) != comparison.judge_route_sha256
            or manifest["config"]["answer"]["model"] != model
        ):
            raise ValueError(
                "Base/checkpoint report differs from frozen comparison contract"
            )
    if base["manifest"]["modes"] != trained["manifest"]["modes"]:
        raise ValueError("Execution modes differ")
    for key in ("top_k", "neighbors", "preprocessing_version", "code", "scope"):
        if base["manifest"][key] != trained["manifest"][key]:
            raise ValueError(
                "Harness scope or retrieval implementation changed during comparison"
            )
    if base["manifest"]["config"].get("embedding") != trained["manifest"]["config"].get(
        "embedding"
    ):
        raise ValueError("Embedding setup differs")
    for key in (
        "context_tokens",
        "evidence_tokens",
        "output_tokens",
        "judge_output_tokens",
        "hermes",
    ):
        if base["manifest"]["config"].get(key) != trained["manifest"]["config"].get(
            key
        ):
            raise ValueError("Generation budget or tool/runtime configuration differs")
    expected = {
        (qid, mode)
        for qid in comparison.question_ids
        for mode in base["manifest"]["modes"]
    }
    indexed = []
    for report in (base, trained):
        records = {
            (row["question_id"], row["mode"]): row for row in report["questions_detail"]
        }
        if set(records) != expected or len(records) != len(report["questions_detail"]):
            raise ValueError("Missing or duplicated planned evaluation records")
        indexed.append(records)
    counts = []
    for records in indexed:
        correct = sum(
            row.get("correct") is True and row["status"] == "graded"
            for row in records.values()
        )
        valid = sum(row["status"] == "graded" for row in records.values())
        invalid = sum(row["status"] == "invalid_final" for row in records.values())
        complete = sum("prediction" in row for row in records.values())
        counts.append(
            {
                "correct": correct,
                "valid_grades": valid,
                "planned": len(expected),
                "success_per_planned": correct / len(expected),
                "completion_rate": complete / len(expected),
                "invalid_final_rate": invalid / len(expected),
                "wilson_95_success_interval": wilson(correct, len(expected)),
            }
        )
    a, b = indexed
    disagreement = [
        {
            "question_id": qid,
            "mode": mode,
            "base_correct": a[(qid, mode)].get("correct"),
            "checkpoint_correct": b[(qid, mode)].get("correct"),
            "base_status": a[(qid, mode)]["status"],
            "checkpoint_status": b[(qid, mode)]["status"],
        }
        for qid, mode in sorted(expected)
        if (a[(qid, mode)].get("correct"), a[(qid, mode)]["status"])
        != (b[(qid, mode)].get("correct"), b[(qid, mode)]["status"])
    ]
    blockers = []
    if counts[1]["valid_grades"] < comparison.minimum_valid_grades:
        blockers.append("insufficient_heldout_sample")
    if counts[1]["completion_rate"] < comparison.minimum_completion:
        blockers.append("completion_gate_failed")
    if counts[1]["invalid_final_rate"] > comparison.maximum_invalid_final_rate:
        blockers.append("invalid_final_gate_failed")
    if counts[1]["success_per_planned"] < counts[0]["success_per_planned"]:
        blockers.append("base_success_regression")
    return {
        "comparison_sha256": comparison.fingerprint,
        "base": counts[0],
        "checkpoint": counts[1],
        "paired_disagreements": disagreement,
        "eligible_for_promotion_review": not blockers,
        "blockers": blockers,
        "production_changed": False,
        "interpretation": "Intervals describe this frozen sample; comparison eligibility does not authorize deployment",
    }
