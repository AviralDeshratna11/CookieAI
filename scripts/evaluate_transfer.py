"""Deterministic held-out contract ablation; NO live model or learned-quality claim."""

import json
from uuid import UUID

from memory.autonomy.handoff import HandoffSpec
from memory.procedures.skills import HandoffSkill, applicability


def evaluate():
    contract = HandoffSkill(
        required_prefixes=["Decision:", "Next:"],
        forbidden_phrases=["handoff prohibited"],
        minimum_sources=1,
    )
    spec = HandoffSpec(project="Held-out project", sources={UUID(int=1): "a" * 64})
    cases = [
        ("Beacon", "Decision: Adopt weekly review\nNext: Assign an owner", True, True),
        ("Orchard", "Decision: Use MariaDB\nNext: Share the review", True, True),
        (
            "Harbor",
            "Decision: Keep the existing stack\nNext: Confirm scope",
            True,
            True,
        ),
        ("Maple", "Decision: Use a checklist\nNext: Prepare agenda", True, True),
        ("No next action", "Decision: Adopt weekly review", False, True),
        ("No decision", "Next: Assign an owner", False, True),
        (
            "Explicit exception",
            "Decision: Adopt weekly review\nNext: Assign an owner\nhandoff prohibited",
            False,
            True,
        ),
        (
            "Stale evidence",
            "Decision: Adopt weekly review\nNext: Assign an owner",
            False,
            False,
        ),
    ]
    rows = []
    for name, text, expected, current in cases:
        checked = applicability(contract, spec, [text], revision_matches=current)
        rows.append(
            {
                "case": name,
                "expected_applicable": expected,
                "baseline_unconditional_reuse": True,
                "gated_reuse": checked["decision"] == "applicable",
                "decision": checked["decision"],
            }
        )
    negative = [row for row in rows if not row["expected_applicable"]]
    return {
        "evidence_kind": "SYNTHETIC deterministic contract ablation",
        "sample_size": len(rows),
        "baseline": "Unconditional reuse after candidate selection; no applicability gates",
        "baseline_incorrect_reuses": sum(
            row["baseline_unconditional_reuse"] for row in negative
        ),
        "gated_incorrect_reuses": sum(row["gated_reuse"] for row in negative),
        "gated_correct_acceptances": sum(
            row["gated_reuse"] and row["expected_applicable"] for row in rows
        ),
        "limitations": [
            "No model inference",
            "No statistical significance",
            "Does not establish retrieval, induction, reasoning or real-world skill quality",
            "Live same-model retrieval-versus-skills comparison deferred until provider setup",
        ],
        "cases": rows,
    }


if __name__ == "__main__":
    print(json.dumps(evaluate(), indent=2))
