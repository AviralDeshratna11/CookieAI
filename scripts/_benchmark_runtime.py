"""Benchmark-only configuration, durable reservations and immutable HTTP replay.

No settings or credentials are read until explicitly requested. This wrapper is
deliberately not a Provider subclass: Hermes must not replace it with an unmetered
Provider when adjusting its timeout.
"""

import hashlib
import json
import os
import sqlite3
import time
from contextlib import contextmanager
from datetime import date
from decimal import ROUND_CEILING, Decimal
from pathlib import Path
from uuid import uuid4

import httpx
from pydantic import SecretStr

from memory.config import Settings
from memory.context.budget import TokenCounter, check_prompt
from models.providers import Provider


class BudgetExceeded(RuntimeError):
    pass


class InvalidCompletion(ValueError):
    def __init__(self, message, response_state=None):
        self.response_state = response_state
        super().__init__(message)


class CallLimitExceeded(RuntimeError):
    pass


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()
    ).hexdigest()


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    try:
        temporary.write_text(
            json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        # Windows readers/virus scanners can briefly deny replacement even when
        # the directory is writable. Retry this local rename, never the API call.
        for attempt in range(6):
            try:
                temporary.replace(path)
                break
            except PermissionError:
                if attempt == 5:
                    raise
                time.sleep(0.05 * 2**attempt)
    finally:
        temporary.unlink(missing_ok=True)


class BenchmarkSettings(Settings):
    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls,
        init_settings,
        env_settings,
        dotenv_settings,
        file_secret_settings,
    ):
        # Supplying values is insufficient: pydantic still parses malformed
        # ambient JSON before resolving precedence. Exclude those sources.
        return (init_settings,)


def isolated_settings(**overrides):
    # Supplying EVERY field explicitly prevents ambient MEMORY_* variables from
    # introducing hosted calls, background models or a production database.
    defaults = {
        name: field.get_default(call_default_factory=True)
        for name, field in Settings.model_fields.items()
    }
    return BenchmarkSettings(_env_file=None, **(defaults | overrides))


def money_units(value):
    try:
        value = Decimal(str(value))
    except ArithmeticError:
        raise ValueError("Money must be an explicit decimal amount") from None
    if not value.is_finite() or value < 0:
        raise ValueError("Money must be finite and nonnegative")
    return int((value * 1_000_000_000).to_integral_value(rounding=ROUND_CEILING))


def usd(units):
    return str(Decimal(units) / 1_000_000_000)


class Ledger:
    """Shared SQLite ledger; pending/uncertain calls retain the full reservation.

    A task ledger cannot be reopened with a larger cap. A deliberate new task
    needs a new ledger and an explicitly approved budget. The cap also applies
    to concurrent processes via BEGIN IMMEDIATE, not just threads.
    """

    def __init__(self, path, max_cost="1", max_calls=100):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        cap = money_units(max_cost)
        self.instance_cap, self.instance_calls = cap, max_calls
        if max_calls < 1:
            raise ValueError(
                "Initial validation is limited to $1 and positive call limits"
            )
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS policy (id INTEGER PRIMARY KEY, cap INTEGER, calls INTEGER);
                CREATE TABLE IF NOT EXISTS requests (
                    id TEXT PRIMARY KEY, stage TEXT, fingerprint TEXT,
                    reserved INTEGER, charged INTEGER, state TEXT, usage TEXT);
                CREATE TABLE IF NOT EXISTS request_claims (
                    fingerprint TEXT PRIMARY KEY, owner TEXT, created_at REAL, state TEXT);
                CREATE TABLE IF NOT EXISTS policy_revisions (
                    plan_sha256 TEXT PRIMARY KEY, prior_cap INTEGER, cap INTEGER,
                    prior_calls INTEGER, calls INTEGER, approval TEXT);
                CREATE TABLE IF NOT EXISTS operations (
                    identity TEXT PRIMARY KEY, request_id TEXT);
            """)
            db.execute("BEGIN IMMEDIATE")
            prior = db.execute("SELECT cap, calls FROM policy WHERE id=1").fetchone()
            if cap > money_units("1") and (
                not prior or cap > prior[0] or max_calls > prior[1]
            ):
                raise ValueError(
                    "Full-run limits require a matching approved policy migration"
                )
            if prior and (cap > prior[0] or max_calls > prior[1]):
                raise ValueError("Cannot increase an existing ledger's limits")
            if not prior:
                db.execute("INSERT INTO policy VALUES (1, ?, ?)", (cap, max_calls))

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        try:
            with db:
                yield db
        finally:
            db.close()

    def reserve(self, stage, fingerprint, units, *, operation=None):
        if type(units) is not int or units < 0:
            raise ValueError("Reservations must be nonnegative integer currency units")
        identity = uuid4().hex
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if (
                operation is not None
                and db.execute(
                    "SELECT 1 FROM operations WHERE identity=?", (operation,)
                ).fetchone()
            ):
                raise ValueError(
                    "Operation already started; reconcile its existing outcome"
                )
            cap, calls = db.execute(
                "SELECT cap, calls FROM policy WHERE id=1"
            ).fetchone()
            cap, calls = min(cap, self.instance_cap), min(calls, self.instance_calls)
            spent, count = db.execute(
                "SELECT COALESCE(SUM(charged),0), COUNT(*) FROM requests"
            ).fetchone()
            if db.execute(
                "SELECT 1 FROM requests WHERE state IN ('missing_usage','overrun') LIMIT 1"
            ).fetchone():
                raise BudgetExceeded(
                    "Unresolved usage/billing mismatch; reconcile before further inference"
                )
            if spent + units > cap or count >= calls:
                raise BudgetExceeded(
                    "Cumulative model-call or dollar allowance exhausted"
                )
            db.execute(
                "INSERT INTO requests VALUES (?, ?, ?, ?, ?, 'pending', NULL)",
                (identity, stage, fingerprint, units, units),
            )
            if operation is not None:
                db.execute("INSERT INTO operations VALUES (?,?)", (operation, identity))
        return identity

    def approve_policy(self, plan, approval):
        """Auditable operator-invoked migration; never called by run execution."""
        approval.require("evaluation", plan.fingerprint)
        cap, calls = money_units(plan.cost.cumulative_cap_usd), plan.cost.max_calls
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute(
                "SELECT 1 FROM request_claims WHERE state='running'"
            ).fetchone():
                raise ValueError(
                    "Cannot change allocation while a request is in flight"
                )
            previous = db.execute("SELECT cap,calls FROM policy WHERE id=1").fetchone()
            spent = db.execute(
                "SELECT COALESCE(SUM(charged),0) FROM requests"
            ).fetchone()[0]
            if cap < spent:
                raise ValueError("Approved cap is below retained spend")
            prior = db.execute(
                "SELECT cap,calls FROM policy_revisions WHERE plan_sha256=?",
                (plan.fingerprint,),
            ).fetchone()
            if prior:
                if prior != (cap, calls):
                    raise ValueError("Allocation identity conflict")
                return
            db.execute(
                "INSERT INTO policy_revisions VALUES (?,?,?,?,?,?)",
                (
                    plan.fingerprint,
                    previous[0],
                    cap,
                    previous[1],
                    calls,
                    json.dumps(approval.model_dump(mode="json")),
                ),
            )
            db.execute("UPDATE policy SET cap=?,calls=? WHERE id=1", (cap, calls))

    @contextmanager
    def request_claim(self, fingerprint):
        owner = uuid4().hex
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute(
                "SELECT 1 FROM request_claims WHERE fingerprint=?", (fingerprint,)
            ).fetchone():
                raise RuntimeError(
                    "Request is claimed or ambiguous; reconcile instead of duplicating inference"
                )
            db.execute(
                "INSERT INTO request_claims VALUES (?,?,?,'running')",
                (fingerprint, owner, time.time()),
            )
            before = db.execute(
                "SELECT COUNT(*) FROM requests WHERE fingerprint=?", (fingerprint,)
            ).fetchone()[0]
        try:
            yield
        except BaseException as error:
            with self.connect() as db:
                after = db.execute(
                    "SELECT COUNT(*) FROM requests WHERE fingerprint=?", (fingerprint,)
                ).fetchone()[0]
                if after > before and not isinstance(error, httpx.HTTPStatusError):
                    db.execute(
                        "UPDATE request_claims SET state='unknown' WHERE fingerprint=? AND owner=?",
                        (fingerprint, owner),
                    )
                else:
                    db.execute(
                        "DELETE FROM request_claims WHERE fingerprint=? AND owner=?",
                        (fingerprint, owner),
                    )
            raise
        else:
            with self.connect() as db:
                db.execute(
                    "DELETE FROM request_claims WHERE fingerprint=? AND owner=?",
                    (fingerprint, owner),
                )

    def settle(self, identity, units, usage):
        if type(units) is not int or units < 0:
            raise ValueError("Settlements must be nonnegative integer currency units")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            reserved = db.execute(
                "SELECT reserved FROM requests WHERE id=?", (identity,)
            ).fetchone()[0]
            # If accounting violated our price/token bound, retain the actual
            # charge and stop. This ledger is not an authoritative billing API.
            db.execute(
                "UPDATE requests SET charged=?, state=?, usage=? WHERE id=?",
                (
                    units,
                    "overrun" if units > reserved else "settled",
                    json.dumps(usage),
                    identity,
                ),
            )
        if units > reserved:
            raise BudgetExceeded(
                "Usage exceeded the declared billing bound; stop and reconcile billing"
            )

    def uncertain(self, identity, *, missing_usage=False):
        with self.connect() as db:
            db.execute(
                "UPDATE requests SET state=? WHERE id=?",
                ("missing_usage" if missing_usage else "uncertain", identity),
            )

    def summary(self):
        with self.connect() as db:
            cap, calls = db.execute(
                "SELECT cap,calls FROM policy WHERE id=1"
            ).fetchone()
            rows = db.execute(
                "SELECT state, COUNT(*), COALESCE(SUM(charged),0) FROM requests GROUP BY state"
            ).fetchall()
        return {
            "cap_usd": usd(cap),
            "call_cap": calls,
            "calls": sum(row[1] for row in rows),
            "spent_or_reserved_usd": usd(sum(row[2] for row in rows)),
            "states": {
                state: {"calls": count, "usd": usd(cost)} for state, count, cost in rows
            },
            "authority": "local conservative ledger, not provider billing",
        }


def validate_route(route, *, embedding=False):
    from urllib.parse import urlparse

    if not route.get("model") or "REPLACE" in route["model"]:
        raise ValueError("Choose an exact account-visible model ID")
    parsed = urlparse(route["base_url"])
    if (
        parsed.scheme != "https"
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Benchmark routes require a credential-free HTTPS URL")
    if parsed.hostname != "api.tokenfactory.nebius.com":
        raise ValueError(
            "This paid profile supports Nebius only; never send its key to NVIDIA's API"
        )
    if not embedding and not route["model"].casefold().startswith("nvidia/"):
        if not route.get("checkpoint"):
            raise ValueError(
                "Select an NVIDIA-authored model or an explicitly bound trained checkpoint"
            )
        from scripts._experiment_contracts import Checkpoint

        provenance = Checkpoint.model_validate(route.get("checkpoint", {}))
        if (
            provenance.inference_model != route["model"]
            or not provenance.artifact_sha256
        ):
            raise ValueError(
                "Checkpoint model requires matching immutable job/artifact provenance"
            )
    if not isinstance(route.get("api_key_env"), str) or not route["api_key_env"]:
        raise ValueError("Specify only the environment variable name for the API key")
    if not 512 <= route.get("template_reserve_tokens", 1024) <= 16384:
        raise ValueError("Template reserve must be between 512 and 16384 tokens")
    if not 4096 <= route.get("context_tokens", 32768) <= 262144:
        raise ValueError("Invalid route context limit")
    if not 0 < route.get("timeout_seconds", 60) <= 300:
        raise ValueError("Timeout must be positive and at most 300 seconds")
    if not 1024 <= route.get("model_response_bytes", 262144) <= 1048576:
        raise ValueError("Response byte bound must be between 1024 and 1048576")
    price = route.get("pricing", {})
    if price.get("currency") != "USD" or price.get("unit") != "per_million_tokens":
        raise ValueError("Explicit USD per-million-token pricing is required")
    if not price.get("source_url", "").startswith("https://") or not price.get(
        "verified_on"
    ):
        raise ValueError("Record the official pricing source and verification date")
    price_host = urlparse(price["source_url"]).hostname or ""
    if price_host != "nebius.com" and not price_host.endswith(".nebius.com"):
        raise ValueError("Use an official Nebius pricing source")
    verified = date.fromisoformat(price["verified_on"])
    if not 0 <= (date.today() - verified).days <= 30:
        raise ValueError("Reverify pricing within 30 days before a paid run")
    money_units(price["input"])
    money_units(price["output"])
    if price.get("output_includes_reasoning") is not True:
        raise ValueError(
            "Reasoning billing must be included in the declared output bound"
        )
    if route.get("bounded_output_verified") is not True:
        raise ValueError(
            "Verify max_tokens bounds all billable completion/reasoning tokens"
        )
    if route.get("completion_limit_parameter", "max_tokens") not in {
        "max_tokens",
        "max_completion_tokens",
    }:
        raise ValueError("Unsupported completion limit parameter")
    if route.get("reasoning_effort") not in {
        None,
        "none",
        "minimal",
        "low",
        "medium",
        "high",
        "xhigh",
        "max",
    }:
        raise ValueError("Unsupported provider reasoning effort")


class MeteredProvider:
    def __init__(
        self,
        route,
        ledger,
        cache_dir,
        stage,
        *,
        replay=False,
        transport=None,
        sleep=time.sleep,
    ):
        self.route, self.ledger, self.stage = route, ledger, stage
        self.cache_dir, self.replay = Path(cache_dir), replay
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.counter = TokenCounter()  # UTF-8 bound; includes serialized envelopes.
        self.transport, self.sleep = transport, sleep
        self.events = []
        self.remaining_calls = None
        self.cache_identity = None
        self.deadline = None

    def consume_call(self):
        if self.remaining_calls is not None:
            if self.remaining_calls <= 0:
                raise CallLimitExceeded(
                    "Per-question stage request allowance exhausted"
                )
            self.remaining_calls -= 1

    def cost(self, inputs, outputs):
        price = self.route["pricing"]
        return money_units(
            (
                Decimal(str(price["input"])) * inputs
                + Decimal(str(price["output"])) * outputs
            )
            / 1_000_000
        )

    def normalize_payload(self, endpoint, payload):
        payload = dict(payload)
        if endpoint == "/chat/completions":
            if (
                self.route.get("completion_limit_parameter") == "max_completion_tokens"
                and "max_tokens" in payload
            ):
                payload["max_completion_tokens"] = payload.pop("max_tokens")
            if self.route.get("reasoning_effort") is not None:
                payload["reasoning_effort"] = self.route["reasoning_effort"]
        return payload

    def post(self, endpoint, payload):
        payload = self.normalize_payload(endpoint, payload)
        key = digest(
            {
                "route": self.route,
                "endpoint": endpoint,
                "payload": payload,
                "cache_identity": self.cache_identity,
            }
        )
        if self.replay or (self.cache_dir / (key + ".json")).exists():
            return self._post(endpoint, payload)
        with self.ledger.request_claim(key):
            return self._post(endpoint, payload)

    def _post(self, endpoint, payload):
        if payload.get("model") != self.route["model"]:
            raise ValueError("Model changed outside the declared benchmark route")
        if endpoint not in {"/embeddings", "/chat/completions"}:
            raise ValueError("Unsupported benchmark endpoint")
        if (
            endpoint == "/chat/completions"
            and self.route.get("completion_limit_parameter") == "max_completion_tokens"
        ):
            payload = dict(payload)
            if "max_tokens" in payload:
                payload["max_completion_tokens"] = payload.pop("max_tokens")
        if (
            endpoint == "/chat/completions"
            and self.route.get("reasoning_effort") is not None
        ):
            payload = {**payload, "reasoning_effort": self.route["reasoning_effort"]}
        fingerprint = digest(
            {
                "route": self.route,
                "endpoint": endpoint,
                "payload": payload,
                "cache_identity": self.cache_identity,
            }
        )
        cache = self.cache_dir / (fingerprint + ".json")
        if cache.exists():
            self.consume_call()
            result = json.loads(cache.read_text(encoding="utf-8"))
            self.events.append(
                {"stage": self.stage, "fingerprint": fingerprint, "cache_hit": True}
            )
            return result
        if self.replay:
            raise FileNotFoundError("Replay cache miss; network is disabled")
        validate_route(self.route, embedding=endpoint == "/embeddings")
        key = os.getenv(self.route["api_key_env"])
        if not key:
            raise ValueError("Missing benchmark API key environment variable")
        # Include templates and provider-specific overhead in the reservation.
        inputs = self.counter.count(payload) + self.route.get(
            "template_reserve_tokens", 1024
        )
        outputs = payload.get("max_completion_tokens", payload.get("max_tokens", 0))
        if endpoint == "/chat/completions":
            if type(outputs) is not int or outputs < 1:
                raise ValueError("Every completion needs a positive output ceiling")
            check_prompt(
                payload["messages"],
                self.counter,
                self.route.get("context_tokens", 32768),
                outputs,
                self.route.get("template_reserve_tokens", 1024),
                payload.get("tools"),
            )
        reservation = self.cost(inputs, outputs)
        attempts = self.route.get("attempts", 1)
        if not 1 <= attempts <= 2:
            raise ValueError("Benchmark permits at most two attempts")
        for attempt in range(attempts):
            timeout = self.route.get("timeout_seconds", 60)
            if self.deadline is not None:
                timeout = min(timeout, self.deadline - time.monotonic())
                if timeout <= 0:
                    raise TimeoutError("Benchmark execution deadline exhausted")
            self.consume_call()
            identity = self.ledger.reserve(self.stage, fingerprint, reservation)
            started = time.monotonic()
            try:
                settings = isolated_settings(
                    provider_base_url=self.route["base_url"],
                    provider_api_key=SecretStr(key),
                    request_timeout_seconds=timeout,
                    model_response_bytes=self.route.get("model_response_bytes", 262144),
                    cloud_disclosure_enabled=True,
                )
                if self.transport is None:
                    result = Provider(settings).post(endpoint, payload)
                else:
                    with httpx.Client(
                        transport=self.transport,
                        timeout=settings.request_timeout_seconds,
                    ) as client:
                        response = client.post(
                            settings.provider_base_url.rstrip("/") + endpoint,
                            json=payload,
                            headers={"Authorization": "Bearer " + key},
                        )
                        response.raise_for_status()
                        result = response.json()
            except Exception as error:
                self.ledger.uncertain(identity)
                self.events.append(
                    {
                        "stage": self.stage,
                        "fingerprint": fingerprint,
                        "cache_hit": False,
                        "error_class": type(error).__name__,
                        "ledger_request_id": identity,
                        "reserved_usd": usd(reservation),
                        "charged_or_reserved_usd": usd(reservation),
                    }
                )
                transient = isinstance(
                    error, httpx.HTTPStatusError
                ) and error.response.status_code in {429, 502, 503, 504}
                # Do not automatically retry ambiguous timeouts/transport errors.
                if not transient or attempt + 1 == attempts:
                    raise
                try:
                    delay = float(error.response.headers.get("Retry-After", 1))
                except ValueError:
                    delay = 1
                if not 0 <= delay <= 10:
                    raise
                self.sleep(delay)
                continue
            # Persist the response before settlement, so a process crash after
            # charging cannot force an unnecessary repeat of a completed request.
            atomic_json(cache, result)
            usage = result.get("usage") if isinstance(result, dict) else None
            if not isinstance(usage, dict):
                usage = {}
            prompt = usage.get("prompt_tokens")
            completion = usage.get(
                "completion_tokens", 0 if endpoint == "/embeddings" else None
            )
            valid = (
                type(prompt) is int
                and prompt >= 0
                and type(completion) is int
                and completion >= 0
            )
            if valid:
                total = usage.get("total_tokens", prompt + completion)
                details = usage.get("completion_tokens_details") or {}
                reasoning = (
                    details.get("reasoning_tokens", 0)
                    if isinstance(details, dict)
                    else None
                )
                valid = (
                    type(total) is int
                    and 0 <= total <= prompt + completion
                    and type(reasoning) is int
                    and 0 <= reasoning <= completion
                )
            if valid:
                self.ledger.settle(identity, self.cost(prompt, completion), usage)
            else:
                self.ledger.uncertain(identity, missing_usage=True)
            event = {
                "stage": self.stage,
                "fingerprint": fingerprint,
                "cache_hit": False,
                "usage": usage,
                "usage_missing": not valid,
                "latency_ms": (time.monotonic() - started) * 1000,
                "ledger_request_id": identity,
                "reserved_usd": usd(reservation),
                "charged_or_reserved_usd": usd(self.cost(prompt, completion))
                if valid
                else usd(reservation),
                "finish_reasons": [
                    choice.get("finish_reason")
                    for choice in (
                        result.get("choices", []) if isinstance(result, dict) else []
                    )
                ],
            }
            self.events.append(event)
            # Save even invalid completions for diagnosis; do not pay to repeat
            # a deterministic length/refusal/format failure on resume.
            return result


def final_content(result, *, allow_tools=False):
    from scripts._response_adapter import classify

    state = classify(result)
    if allow_tools and state.state == "tool_call":
        return None
    if state.state != "final":
        raise InvalidCompletion("Invalid completion state: " + state.state, state.state)
    return state.final
