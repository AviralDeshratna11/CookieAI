"""Offline data hygiene and approval-gated, supported fine-tuning job lifecycle."""

import json
import random
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Literal

import httpx
from pydantic import Field, model_validator

from memory.context.budget import TokenCounter
from scripts._benchmark_runtime import atomic_json, digest, money_units
from scripts._experiment_contracts import Checkpoint, Contract

EXPOSED = [
    "9d25d4e0",
    "gpt4_1e4a8aeb",
    "35a27287",
    "2698e78f",
    "f685340e_abs",
    "7a8d0b71",
    "a82c026e",
]


class ChatMessage(Contract):
    role: Literal["system", "user", "assistant", "tool"]
    content: str | None = None
    tool_calls: list[dict] | None = None
    tool_call_id: str | None = None


class TrainingExample(Contract):
    example_id: str
    group_id: str
    source_ids: list[str]
    source_hashes: list[str]
    origin: Literal["independent_synthetic", "consented_corpus"]
    permission: str = Field(min_length=1)
    consented: bool
    target_reviewed: bool
    category: Literal[
        "calendar", "update", "evidence", "preference", "abstention", "tool_protocol"
    ]
    messages: list[ChatMessage] = Field(min_length=2)
    tools: list[dict] = Field(default_factory=list)

    @model_validator(mode="after")
    def clean_targets(self):
        if (
            not self.consented
            or not self.target_reviewed
            or not self.source_ids
            or not self.source_hashes
        ):
            raise ValueError("Consent, lineage and reviewed targets are required")
        if self.messages[-1].role != "assistant" or not self.messages[-1].content:
            raise ValueError("Example must end with a clean assistant target")
        serialized = json.dumps([m.model_dump() for m in self.messages]).lower()
        if any(
            marker in serialized
            for marker in (
                "<think>",
                "</think>",
                '"reasoning_content"',
                '"reasoning"',
                "correct answer:",
                "answer_session_ids",
            )
        ):
            raise ValueError(
                "Reasoning traces or evaluation labels cannot become training targets"
            )
        pending, seen = set(), set()
        for message in self.messages:
            if message.tool_calls:
                if message.role != "assistant" or pending:
                    raise ValueError("Invalid tool trajectory")
                for call in message.tool_calls:
                    if (
                        not call.get("id")
                        or call["id"] in seen
                        or call.get("type") != "function"
                    ):
                        raise ValueError("Invalid tool call ID")
                    if not isinstance(json.loads(call["function"]["arguments"]), dict):
                        raise ValueError("Tool arguments must be JSON objects")
                    seen.add(call["id"])
                    pending.add(call["id"])
            elif message.role == "tool":
                if message.tool_call_id not in pending:
                    raise ValueError("Tool result ID mismatch")
                pending.remove(message.tool_call_id)
            elif pending:
                raise ValueError("Tool result is missing")
        if pending:
            raise ValueError("Unresolved tool calls")
        return self

    def provider_record(self):
        messages = []
        for message in self.messages:
            messages.append(
                message.model_dump(exclude={"schema_version"}, exclude_none=True)
            )
        record = {"messages": messages}
        if self.tools:
            record["tools"] = self.tools
        return record


def normalize(text):
    return " ".join(re.findall(r"\w+", text.casefold()))


def text_signatures(text, width=12):
    words = normalize(text).split()
    return {digest(words[i : i + width]) for i in range(max(0, len(words) - width + 1))}


def redact_pii(text):
    text, count = re.subn(
        r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "[REDACTED_EMAIL]", text
    )

    def replace_phone(match):
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", match.group()):
            return match.group()
        return "[REDACTED_PHONE]"

    updated = re.sub(r"(?<!\w)\+?\d[\d ()-]{7,}\d(?!\w)", replace_phone, text)
    return updated, count + (updated != text)


def independent_examples(groups=24, seed=941):
    """Authored templates with deterministic targets; no benchmark/cache inputs."""
    rng, result = random.Random(seed), []
    categories = [
        "calendar",
        "update",
        "evidence",
        "preference",
        "abstention",
        "tool_protocol",
    ]
    for index in range(groups):
        group = f"authored-person-{index}"
        category = categories[index % len(categories)]
        first = date(2019 + index % 6, 1, 1) + timedelta(days=rng.randrange(350))
        gap = rng.randrange(2, 25)
        last = first + timedelta(days=gap)
        if category == "calendar":
            question = f"On {first.isoformat()} I booked a ferry. On {last.isoformat()} I boarded. How many elapsed calendar days passed?"
            answer = f"{gap} days"
        elif category == "update":
            question = f"As of {first.isoformat()} my desk was in room A{index}. On {last.isoformat()} I moved it to room B{index}. Where is it now?"
            answer = f"Room B{index}."
        elif category == "evidence":
            question = f"Session one: I borrowed {index + 2} maps. Session two: I borrowed {index + 3} more maps. How many maps did I borrow in total?"
            answer = f"{2 * index + 5} maps."
        elif category == "preference":
            question = f"Profile {index}: I like walking and quiet museums. Suggest an afternoon activity consistent with that preference."
            answer = "Take a walk to a quiet museum and spend the afternoon exploring its exhibits."
        elif category == "abstention":
            question = f"Profile {index}: I bought a green travel bag. What is its serial number?"
            answer = "The serial number was not provided."
        else:
            question = f"Use the calculator to evaluate {index + 2} + {gap}."
            answer = str(index + 2 + gap)
        messages = [ChatMessage(role="user", content=question)]
        tools = []
        if category == "tool_protocol":
            from memory.agent.hermes_tools import TOOL_SCHEMAS

            tools = [{"type": "function", "function": TOOL_SCHEMAS[0]}]
            messages.extend(
                [
                    ChatMessage(
                        role="assistant",
                        tool_calls=[
                            {
                                "id": f"calculate-{index}",
                                "type": "function",
                                "function": {
                                    "name": "cookieai_calculate",
                                    "arguments": json.dumps(
                                        {"expression": f"{index + 2}+{gap}"}
                                    ),
                                },
                            }
                        ],
                    ),
                    ChatMessage(
                        role="tool",
                        tool_call_id=f"calculate-{index}",
                        content=json.dumps({"value": answer}),
                    ),
                ]
            )
        messages.append(ChatMessage(role="assistant", content=answer))
        result.append(
            TrainingExample(
                example_id=f"authored-{seed}-{index}",
                group_id=group,
                source_ids=[group],
                source_hashes=[digest(question)],
                origin="independent_synthetic",
                permission="Repository-authored synthetic fixture; development use",
                consented=True,
                target_reviewed=True,
                category=category,
                messages=messages,
                tools=tools,
            )
        )
    return result


def benchmark_lineage(instances):
    sources, hashes, grams = set(EXPOSED), set(), set()
    for row in instances:
        sources.add(row["question_id"])
        sources.update(row["haystack_session_ids"])
        # Conversation identity works across oracle/S/M variants, regardless of
        # question ID or whether the history is reordered.
        for turns in row["haystack_sessions"]:
            hashes.add(
                digest([(turn["role"], normalize(turn["content"])) for turn in turns])
            )
            for turn in turns:
                hashes.add(digest(normalize(turn["content"])))
                grams.update(text_signatures(turn["content"]))
        grams.update(text_signatures(row["question"]))
    return sources, hashes, grams


def prepare_training(
    examples, destination, *, benchmarks=(), revoked_sources=(), seed=941
):
    examples = [TrainingExample.model_validate(row) for row in examples]
    forbidden_ids, forbidden_hashes, forbidden_grams = benchmark_lineage(benchmarks)
    forbidden_ids.update(EXPOSED)
    forbidden_ids.update(revoked_sources)
    # A deletion or benchmark overlap taints the entire linked conversation,
    # including examples that omitted the revoked source from their own list.
    tainted_groups = set()
    tainted_sources = set(forbidden_ids)
    tainted_hashes = set(forbidden_hashes)
    while True:
        previous = (len(tainted_groups), len(tainted_sources), len(tainted_hashes))
        for row in examples:
            if (
                row.group_id in tainted_groups
                or set(row.source_ids) & tainted_sources
                or set(row.source_hashes) & tainted_hashes
            ):
                tainted_groups.add(row.group_id)
                tainted_sources.update(row.source_ids)
                tainted_hashes.update(row.source_hashes)
        if previous == (len(tainted_groups), len(tainted_sources), len(tainted_hashes)):
            break
    kept, excluded, seen, groups = [], [], set(), {}
    redacted_review = []
    for row in examples:
        text = " ".join(message.content or "" for message in row.messages)
        if row.origin == "consented_corpus":
            preview, changes = redact_pii(
                json.dumps(row.provider_record(), ensure_ascii=False)
            )
            if changes:
                excluded.append(
                    {
                        "example_id": row.example_id,
                        "reason": "redaction_requires_target_review",
                    }
                )
                redacted_review.append(
                    {
                        "example_sha256": digest(row.example_id),
                        "redacted_record": json.loads(preview),
                        "target_reviewed": False,
                    }
                )
                continue
        fingerprint = digest(normalize(text))
        reason = None
        if (
            row.group_id in tainted_groups
            or set(row.source_ids) & forbidden_ids
            or row.example_id in forbidden_ids
        ):
            reason = "forbidden_or_revoked_lineage"
        elif set(row.source_hashes) & forbidden_hashes:
            reason = "benchmark_source_overlap"
        elif text_signatures(text) & forbidden_grams:
            reason = "benchmark_phrase_overlap"
        elif fingerprint in seen:
            reason = "duplicate"
        if reason:
            excluded.append({"example_id": row.example_id, "reason": reason})
            continue
        seen.add(fingerprint)
        kept.append(row)
        groups.setdefault(row.group_id, []).append(row)
    # Connected components ensure source IDs/hashes shared across distinct users
    # cannot land in different partitions.
    parent = {group: group for group in groups}

    def root(group):
        while parent[group] != group:
            parent[group] = parent[parent[group]]
            group = parent[group]
        return group

    owners = {}
    for row in kept:
        for source in row.source_ids + row.source_hashes:
            if source in owners:
                parent[root(row.group_id)] = root(owners[source])
            owners[source] = row.group_id
    components = sorted({root(group) for group in groups})
    random.Random(seed).shuffle(components)
    if len(components) < 3:
        raise ValueError(
            "Need at least three independent lineage groups for train/dev/test"
        )
    hold = max(1, len(components) // 10)
    split = {
        group: "test" if i < hold else "validation" if i < hold * 2 else "train"
        for i, group in enumerate(components)
    }
    buckets = {
        name: [row for row in kept if split[root(row.group_id)] == name]
        for name in ("train", "validation", "test")
    }
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    artifacts = {}
    for name, rows in buckets.items():
        records = [row.provider_record() for row in rows]
        path = destination / f"{name}.jsonl"
        from uuid import uuid4

        temporary = path.with_name(path.name + uuid4().hex + ".tmp")
        temporary.write_text(
            "".join(
                json.dumps(record, ensure_ascii=False) + "\n" for record in records
            ),
            encoding="utf-8",
        )
        temporary.replace(path)
        artifacts[name] = {
            "file": str(path),
            "sha256": digest(records),
            "examples": len(rows),
            "token_upper_bound": sum(
                TokenCounter().count(record) for record in records
            ),
        }
    manifest = {
        "schema_version": 1,
        "seed": seed,
        "artifacts": artifacts,
        "examples": [
            {
                "example_id": row.example_id,
                "group_id": row.group_id,
                "sources": row.source_ids,
                "source_hashes": row.source_hashes,
                "split": split[root(row.group_id)],
                "origin": row.origin,
                "permission": row.permission,
                "category": row.category,
            }
            for row in kept
        ],
        "excluded": excluded,
        "benchmark_instances_checked": len(benchmarks),
        "development_exposed_ids": EXPOSED,
        "leakage_check": "group/source/hash components plus normalized 12-word overlap; not proof against semantic paraphrases",
        "provider_schema_status": "chat/tool JSONL generated; exact selected-model training-schema verification required before upload",
        "uploaded": False,
    }
    atomic_json(destination / "manifest.json", manifest)
    atomic_json(destination / "redacted-review.json", redacted_review)
    atomic_json(
        destination / "data-card.json",
        {
            "synthetic": all(row.origin == "independent_synthetic" for row in kept),
            "purpose": "Offline pipeline smoke data, not a production training corpus",
            "examples": len(kept),
            "categories": {
                kind: sum(row.category == kind for row in kept)
                for kind in sorted({row.category for row in kept})
            },
            "redaction": "No real-user data generated; custom corpus consent/review required",
            "revoked_sources": list(revoked_sources),
        },
    )
    return manifest


class TrainingCapability(Contract):
    model: str
    supported: bool = False
    account_verified: bool = False
    schema_verified: bool = False
    credit_eligibility_verified: bool = False
    methods: list[Literal["lora", "full"]] = Field(default_factory=list)
    source_url: str
    checked_on: str
    pricing_verified: bool = False
    max_context_tokens: int | None = None


class TrainingPlan(Contract):
    adapter_version: Literal["nebius-sft-v1"] = "nebius-sft-v1"
    model: str
    method: Literal["lora", "full"] = "lora"
    capability: TrainingCapability
    dataset_manifest_sha256: str
    train_file_sha256: str
    validation_file_sha256: str
    epochs: int = Field(default=1, ge=1, le=10)
    batch_size: int = Field(default=1, ge=1, le=64)
    learning_rate: float = Field(default=0.00001, gt=0, le=0.01)
    seed: int = 941
    context_tokens: int = Field(default=8192, ge=8192, le=131072)
    lora_rank: int = Field(default=8, ge=8, le=128)
    maximum_liability_usd: str | None = None
    cost_components: dict[str, str] = Field(default_factory=dict)

    @property
    def fingerprint(self):
        return digest(self.model_dump(mode="json"))

    def blockers(self):
        cap = self.capability
        if self.model != cap.model or not cap.supported or not cap.account_verified:
            return ["training_blocked: unsupported_model_or_account"]
        result = []
        try:
            age = (date.today() - date.fromisoformat(cap.checked_on)).days
        except ValueError:
            age = 999
        if not 0 <= age <= 30:
            result.append("training_capability_snapshot_stale")
        if self.method not in cap.methods:
            result.append("unsupported_training_method")
        if not all(
            (cap.schema_verified, cap.credit_eligibility_verified, cap.pricing_verified)
        ):
            result.append("training_schema_pricing_or_credit_eligibility_unverified")
        if (
            cap.max_context_tokens is None
            or self.context_tokens > cap.max_context_tokens
        ):
            result.append("training_context_limit_unverified")
        if self.maximum_liability_usd is None or not self.cost_components:
            result.append("maximum_liability_unverified")
        else:
            if sum(
                money_units(value) for value in self.cost_components.values()
            ) > money_units(self.maximum_liability_usd):
                result.append("cost_components_exceed_maximum_liability")
        return result


class TrainingJob(Contract):
    plan_sha256: str
    state: Literal[
        "PLANNED",
        "DATA_VALIDATED",
        "READY_FOR_APPROVAL",
        "SUBMITTING",
        "QUEUED",
        "RUNNING",
        "SUCCEEDED",
        "FAILED",
        "CANCEL_REQUESTED",
        "CANCELLED",
        "UNKNOWN",
    ] = "PLANNED"
    provider_job_id: str | None = None
    training_file_id: str | None = None
    validation_file_id: str | None = None
    reservation_id: str | None = None
    checkpoint: Checkpoint | None = None
    history: list[dict] = Field(default_factory=list)

    def transition(self, state):
        allowed = {
            "PLANNED": {"DATA_VALIDATED"},
            "DATA_VALIDATED": {"READY_FOR_APPROVAL"},
            "READY_FOR_APPROVAL": {"SUBMITTING"},
            "SUBMITTING": {"QUEUED", "RUNNING", "UNKNOWN", "FAILED"},
            "QUEUED": {
                "RUNNING",
                "FAILED",
                "CANCEL_REQUESTED",
                "CANCELLED",
                "SUCCEEDED",
            },
            "RUNNING": {"SUCCEEDED", "FAILED", "CANCEL_REQUESTED", "CANCELLED"},
            "CANCEL_REQUESTED": {"CANCELLED", "SUCCEEDED", "FAILED", "UNKNOWN"},
            "UNKNOWN": {"QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED"},
        }
        if state == self.state:
            return
        if state not in allowed.get(self.state, set()):
            raise ValueError("Invalid training job transition")
        self.history.append({"from": self.state, "to": state})
        self.state = state


class NebiusTrainingAdapter:
    """Documented endpoints; no retries on upload/submission ambiguity.

    Network credentials/client are explicitly injected, never read on import or
    planning. Mutation methods require matching per-action approval. Job liability
    is reserved before the first upload and held until explicit reconciliation.
    """

    BASE = "https://api.tokenfactory.nebius.com/v1"

    def __init__(self, client, ledger):
        self.client, self.ledger = client, ledger

    def save(self, job, path):
        atomic_json(path, job.model_dump(mode="json"))

    def upload(self, plan, job, path, train_path, validation_path, approval):
        with self.ledger.request_claim("training-upload:" + plan.fingerprint):
            return self._upload(plan, job, path, train_path, validation_path, approval)

    def _upload(self, plan, job, path, train_path, validation_path, approval):
        approval.require("training_upload", plan.fingerprint)
        if plan.blockers():
            raise ValueError("; ".join(plan.blockers()))
        if (
            job.plan_sha256 != plan.fingerprint
            or job.state != "READY_FOR_APPROVAL"
            or job.reservation_id
        ):
            raise ValueError(
                "Job already submitted/uploaded or identity changed; reconcile first"
            )
        for name, source, expected in (
            ("training", train_path, plan.train_file_sha256),
            ("validation", validation_path, plan.validation_file_sha256),
        ):
            records = [
                json.loads(line)
                for line in Path(source).read_text(encoding="utf-8").splitlines()
                if line
            ]
            if digest(records) != expected:
                raise ValueError(name + " artifact hash mismatch")
            if not records:
                raise ValueError(name + " dataset is empty")
            for index, record in enumerate(records):
                if not isinstance(record, dict) or not isinstance(
                    record.get("messages"), list
                ):
                    raise ValueError(name + " dataset record lacks messages")
                messages = [
                    ChatMessage.model_validate(message)
                    for message in record["messages"]
                ]
                if (
                    not messages
                    or messages[-1].role != "assistant"
                    or not messages[-1].content
                ):
                    raise ValueError(name + " record lacks a final assistant target")
                if TokenCounter().count(record) > plan.context_tokens:
                    raise ValueError(
                        f"{name} record {index} exceeds the conservative training context ceiling"
                    )
                text = json.dumps(record).lower()
                if any(
                    marker in text
                    for marker in (
                        "<think>",
                        "</think>",
                        "reasoning_content",
                        "answer_session_ids",
                    )
                ):
                    raise ValueError(
                        name + " record contains reasoning or evaluation labels"
                    )
        job.reservation_id = self.ledger.reserve(
            "training_liability",
            plan.fingerprint,
            money_units(plan.maximum_liability_usd),
            operation="training-upload:" + plan.fingerprint,
        )
        self.save(job, path)
        try:
            for attribute, source in (
                ("training_file_id", train_path),
                ("validation_file_id", validation_path),
            ):
                call = self.ledger.reserve("training_upload_http", plan.fingerprint, 0)
                with open(source, "rb") as stream:
                    response = self.client.post(
                        self.BASE + "/files",
                        data={"purpose": "fine-tune"},
                        files={"file": stream},
                    )
                response.raise_for_status()
                self.ledger.settle(
                    call, 0, {"covered_by_liability": job.reservation_id}
                )
                setattr(job, attribute, response.json()["id"])
                self.save(job, path)
        except BaseException:
            self.ledger.uncertain(job.reservation_id)
            job.history.append({"upload": "unknown; do not retry automatically"})
            self.save(job, path)
            raise

    def submit(self, plan, job, path, approval):
        with self.ledger.request_claim("training-submit:" + plan.fingerprint):
            return self._submit(plan, job, path, approval)

    def _submit(self, plan, job, path, approval):
        approval.require("training_submit", plan.fingerprint)
        if (
            plan.blockers()
            or job.plan_sha256 != plan.fingerprint
            or not job.training_file_id
            or not job.validation_file_id
            or not job.reservation_id
            or job.state != "READY_FOR_APPROVAL"
        ):
            raise ValueError("Training prerequisites incomplete")
        job.transition("SUBMITTING")
        self.save(job, path)
        payload = {
            "model": plan.model,
            "training_file": job.training_file_id,
            "validation_file": job.validation_file_id,
            "seed": plan.seed,
            "hyperparameters": {
                "n_epochs": plan.epochs,
                "batch_size": plan.batch_size,
                "learning_rate": plan.learning_rate,
                "context_length": plan.context_tokens,
                "lora": plan.method == "lora",
            },
        }
        if plan.method == "lora":
            payload["hyperparameters"].update(
                lora_r=plan.lora_rank, lora_alpha=plan.lora_rank
            )
        try:
            call = self.ledger.reserve(
                "training_submit_http",
                plan.fingerprint,
                0,
                operation="training-submit:" + plan.fingerprint,
            )
            response = self.client.post(self.BASE + "/fine_tuning/jobs", json=payload)
            response.raise_for_status()
            job.provider_job_id = response.json()["id"]
            self.ledger.settle(call, 0, {"covered_by_liability": job.reservation_id})
            job.transition("QUEUED")
        except BaseException:
            job.transition("UNKNOWN")
            self.save(job, path)
            raise
        self.save(job, path)
        return job

    def refresh(self, job, path):
        if not job.provider_job_id:
            raise ValueError("Unknown provider job ID; cannot resubmit")
        response = self.metadata_request(
            job, "GET", "/fine_tuning/jobs/" + job.provider_job_id
        )
        state = {
            "queued": "QUEUED",
            "validating_files": "QUEUED",
            "running": "RUNNING",
            "succeeded": "SUCCEEDED",
            "failed": "FAILED",
            "cancelled": "CANCELLED",
        }.get(response.json().get("status"))
        if state is None:
            raise ValueError("Unrecognized provider job status")
        if job.state == "CANCEL_REQUESTED" and state in {"RUNNING", "QUEUED"}:
            return job
        job.transition(state)
        self.save(job, path)
        return job

    def cancel(self, job, path, approval, plan):
        approval.require("training_submit", plan.fingerprint)
        if not job.provider_job_id:
            raise ValueError("No known provider job")
        job.transition("CANCEL_REQUESTED")
        self.save(job, path)
        try:
            self.metadata_request(
                job, "POST", "/fine_tuning/jobs/" + job.provider_job_id + "/cancel"
            )
        except httpx.HTTPError:
            job.transition("UNKNOWN")
            self.save(job, path)
            raise
        # An acknowledgment is not a terminal cancellation and releases no funds.
        return job

    def events(self, job):
        if not job.provider_job_id:
            raise ValueError("Provider job ID is unknown")
        response = self.metadata_request(
            job, "GET", "/fine_tuning/jobs/" + job.provider_job_id + "/events"
        )
        return response.json()

    def checkpoints(self, job):
        if job.state != "SUCCEEDED" or not job.provider_job_id:
            raise ValueError("Successful provider job required")
        response = self.metadata_request(
            job, "GET", "/fine_tuning/jobs/" + job.provider_job_id + "/checkpoints"
        )
        return response.json()

    def metadata_request(self, job, method, path):
        identity = self.ledger.reserve("training_metadata_http", job.plan_sha256, 0)
        try:
            response = self.client.request(method, self.BASE + path)
            response.raise_for_status()
            self.ledger.settle(
                identity, 0, {"covered_by_liability": job.reservation_id}
            )
            return response
        except BaseException:
            self.ledger.uncertain(identity)
            raise

    def bind_checkpoint(self, job, path, checkpoint):
        if job.state != "SUCCEEDED" or checkpoint.job_id != job.provider_job_id:
            raise ValueError("Checkpoint must identify the successful immutable job")
        if not re.fullmatch(r"[0-9a-f]{64}", checkpoint.artifact_sha256):
            raise ValueError(
                "Verify downloaded checkpoint artifact SHA256 before binding"
            )
        job.checkpoint = checkpoint
        self.save(job, path)

    def reconcile_liability(self, job, actual_usd, billing_reference):
        if (
            job.state not in {"SUCCEEDED", "FAILED", "CANCELLED"}
            or not job.reservation_id
            or not billing_reference
        ):
            raise ValueError(
                "Terminal status plus authoritative billing reference required"
            )
        self.ledger.settle(
            job.reservation_id,
            money_units(actual_usd),
            {"billing_reference": billing_reference, "job_id": job.provider_job_id},
        )


def promotion_plan(
    checkpoint, base_route, trained_report, *, minimum_completion=0.95, base_report=None
):
    """Reviewable routing artifact; deliberately does not change any deployment."""
    if (
        trained_report.get("manifest", {}).get("evaluation_plan_sha256")
        != checkpoint.evaluation_plan_sha256
    ):
        raise ValueError("Checkpoint evaluation provenance mismatch")
    blockers = []
    if (trained_report.get("completion_rate", 0) or 0) < minimum_completion:
        blockers.append("heldout_completion_gate_failed")
    if trained_report.get("valid_grades", 0) < 30:
        blockers.append("insufficient_heldout_sample")
    if base_report is None:
        blockers.append("paired_base_report_missing")
    elif (
        base_report.get("manifest", {}).get("evaluation_plan_sha256")
        != checkpoint.evaluation_plan_sha256
    ):
        blockers.append("base_comparison_provenance_mismatch")
    elif (trained_report.get("all_attempted_success_rate", 0) or 0) < (
        base_report.get("all_attempted_success_rate", 0) or 0
    ):
        blockers.append("base_success_regression")
    ready = not blockers
    return {
        "checkpoint": checkpoint.model_dump(mode="json"),
        "candidate_route": {**base_route, "model": checkpoint.inference_model},
        "rollback_route": base_route,
        "eligible_for_review": ready,
        "production_changed": False,
        "blockers": blockers,
        "promotion_requires_explicit_approval": True,
    }
