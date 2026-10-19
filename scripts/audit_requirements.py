"""Build a traceable specification inventory; absence of evidence is never completion."""

import argparse
import hashlib
import re
from pathlib import Path


def area(number):
    groups = [
        (
            {6, 10, 11, 12, 13, 14, 49, 50, 51, 52, 53},
            "memory/service.py",
            "tests/integration/test_foundation.py",
            "Reference §§2–3: canonical stores, extraction, rolling context",
            "Real multi-turn extraction accuracy and complex contradiction reasoning remain unmeasured.",
        ),
        (
            {7, 28},
            "memory/entities/store.py",
            "tests/integration/test_hybrid.py",
            "Reference §2: separate entity vectors and linked memories",
            "Ambiguous pronoun/entity resolution and proposed identity links need broader evaluation.",
        ),
        (
            {8, 30, 31},
            "memory/graph/service.py",
            "tests/integration/test_graph.py",
            "Master extension to linked entity memories",
            "Namespace-wide edge scans need indexed adjacency retrieval and capacity measurements.",
        ),
        (
            {15, 96, 97, 98},
            "memory/episodes/service.py",
            "tests/integration/test_episodes.py",
            "Reference §3: procedural turn evidence",
            "Task segmentation beyond session/time and replay identity need further work.",
        ),
        (
            {16, 43, 45, 99},
            "memory/experiences/service.py",
            "tests/integration/test_experience.py",
            "Master extension: experiences from episodes",
            "Structural dimensions rely on supplied observations; representative extraction evaluation remains.",
        ),
        (
            {17, 44},
            "memory/procedures/service.py",
            "tests/integration/test_procedures.py",
            "Reference §3: procedural memory",
            "Broader sequence induction and real outcome evaluation remain.",
        ),
        (
            {18},
            "memory/goals/service.py",
            "tests/integration/test_transfer.py",
            "Master extension: goals",
            "Cross-user administrative policy remains incomplete.",
        ),
        (
            {19, 56},
            "memory/goals/prospective.py",
            "tests/integration/test_prospective_feedback.py",
            "Master extension: prospective activation",
            "Lifecycle and explicit trigger matching work; automatic inferred opportunities and context-stage integration remain partial.",
        ),
        (
            {20, 21, 22, 23, 24, 57, 58, 59},
            "memory/context/transfer.py",
            "tests/integration/test_transfer.py",
            "Reference §1: cross-session and cross-agent continuity",
            "Persistent asynchronous autobiography and managed organization federation remain incomplete.",
        ),
        (
            {25, 26, 27, 29, 32, 60, 63},
            "memory/service.py",
            "tests/integration/test_hybrid.py",
            "Reference §4: overfetch, lexical/entity reranking; master expands independent candidate sources",
            "Exact corpus BM25 and graph scans remain; latency targets are not certified. Optional predictive prefetch is partial.",
        ),
        (
            {35, 36, 37, 42, 46, 54, 55, 66, 69},
            "memory/reflection/engine.py",
            "tests/integration/test_reflection.py",
            "Master extension: evidence-backed reflection",
            "Tool/configuration failure mining works with real proposal/critic calls. Other mining families, calibrated confidence and complete typed finding metadata remain partial.",
        ),
        (
            {38, 39, 40, 41, 47, 48},
            "memory/serendipity/engine.py",
            "tests/integration/test_serendipity.py",
            "Master extension: controlled association",
            "Structural exploration works; comprehensive neighbor families, real-model analogy evaluation and idle-compute scheduling remain partial.",
        ),
        (
            {33, 34, 70, 71, 91, 100},
            "apps/worker/main.py",
            "tests/integration/test_dispatcher.py",
            "Master extension: durable background loop",
            "Persistent service and event-triggered reflection run. Long-job lease renewal, complete event taxonomy and broader recovery tests remain.",
        ),
        (
            {64, 65, 67, 68},
            "database/repositories/memory.py",
            "tests/integration/test_privacy.py",
            "Reference §5: synchronized deletion; master expands privacy",
            "Local RLS/ACL/deletion tests exist; deployment TLS, encryption, backup erasure and distributed limits need an actual deployment.",
        ),
        (
            {72, 73, 74, 75, 76, 77, 78, 79, 80, 81},
            "docs/verification.md",
            "tests/integration/test_reflection.py",
            "Reference §§1,4,5: continuity, retrieval, deletion",
            "Controlled tests and small real-model evaluation exist; full metric suite and sustained representative evaluation remain.",
        ),
        (
            {82},
            "memory/policy.py",
            "tests/unit/test_policy.py",
            "Reference §§3–4: configurable extraction/retrieval",
            "New worker/model settings are environment-configurable; all-settings tenant overrides remain partial.",
        ),
        (
            {83, 84},
            "models/providers.py",
            "tests/unit/test_provider_formats.py",
            "Reference §5: swappable open-source model stack",
            "Actual generation/embedding adapters work; all declared model interfaces and cost-routing policies are not fully implemented.",
        ),
        (
            {61, 62},
            "apps/api/main.py",
            "tests/integration/test_api.py",
            "Reference §1: tool and automatic access",
            "REST/tool coverage exists; no separate chat UI is promised. Validate every master endpoint against generated OpenAPI.",
        ),
        (
            {94, 95},
            "memory/schemas.py",
            "tests/unit/test_schemas.py",
            "Reference §5 and master future modality extension",
            "Artifact references exist; modality-specific pipelines are unverified and do not constitute implemented image/audio understanding.",
        ),
    ]
    for numbers, *details in groups:
        if number in numbers:
            return details
    return [
        "architecture.md",
        "docs/phase-ledger.md",
        "Cross-cutting specification or deliverable",
        "Requires requirement-specific review; architecture and passing fixtures alone are not acceptance evidence.",
    ]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("spec", type=Path)
    args = parser.parse_args()
    source = args.spec.read_text(encoding="utf-8-sig")
    matches = list(
        re.finditer(r"(?m)^-{20,}\s*\n(\d+)\. ([^\n]+)\n-{20,}\s*\n", source)
    )
    assert {int(m[1]) for m in matches} == set(range(108))
    output = [
        "# Master requirements traceability matrix",
        "",
        "Source SHA-256: `" + hashlib.sha256(args.spec.read_bytes()).hexdigest() + "`.",
        "",
        "All 108 sections (0–107) are inventoried below, followed by source clause groups with stable IDs. "
        "A partial section means code exists but its entire requirement set is not proven. "
        "Individual clauses are explicitly unverified until requirement-specific evidence is assigned; "
        "this inventory is not a claim that a complete clause-by-clause acceptance audit has passed.",
        "",
        "Current real-model evidence: `docs/live-acceptance-results.json`. "
        "Controlled regression evidence: `docs/verification.md`. See `docs/completion-status.md` for remaining work.",
        "",
        "| ID | Requirement area | Status | Implementation | Evidence entry point | Reference | Remaining work |",
        "|---|---|---|---|---|---|---|",
    ]
    sections = []
    for index, match in enumerate(matches):
        number, title = int(match[1]), match[2].strip()
        body = source[
            match.end() : matches[index + 1].start()
            if index + 1 < len(matches)
            else len(source)
        ]
        implementation, evidence, reference, gap = area(number)
        assert Path(implementation).exists() and Path(evidence).exists()
        output.append(
            f"| M{number:03} | {title} | partial | [{implementation}](../{implementation}) | [{evidence}](../{evidence}) | {reference} | {gap} |"
        )
        sections.append((number, title, body, match.end()))
    output += [
        "",
        "## Source clause groups",
        "",
        "Each paragraph, schema field group, list, or example retains a source-line reference. "
        "Examples are not independent promises; their containing section controls interpretation. "
        "Use the implementation, evidence entry point and remaining-work columns above when resolving each clause.",
    ]
    total = 0
    for number, title, body, offset in sections:
        output += [
            "",
            f"### M{number:03}: {title}",
            "",
            "| Clause | Source line | Requirement fragment | Status |",
            "|---|---|---|---|",
        ]
        for item, paragraph in enumerate(
            re.finditer(r"\S(?:[^\n]|\n(?!\s*\n))*", body), 1
        ):
            fragment = (
                " ".join(paragraph[0].split()).replace("|", "\\|").replace("`", "'")
            )
            if not fragment:
                continue
            line = source.count("\n", 0, offset + paragraph.start()) + 1
            output.append(
                f"| M{number:03}.{item:03} | {line} | {fragment} | unverified |"
            )
            total += 1
    Path("docs/requirements-matrix.md").write_text(
        "\n".join(output) + "\n", encoding="utf-8"
    )
    print(
        f"Inventoried {len(matches)} sections and {total} clause groups; no unsupported completion claims."
    )


if __name__ == "__main__":
    main()
