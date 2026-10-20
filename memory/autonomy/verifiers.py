"""Deterministic checks owned by CookieAI, never by the planning model."""

import hashlib
import json
from decimal import Decimal, InvalidOperation

from memory.agent.hermes_tools import execute_tool
from memory.autonomy.contracts import Verification
from memory.schemas import utcnow


def verify(spec, workspace, receipts, *, guard=lambda: None):
    guard()
    evidence = {}
    verdict, limitations = "INCONCLUSIVE", []
    try:
        if spec.kind == "DECIMAL_RESULT":
            if spec.step_index >= len(receipts) or not receipts[spec.step_index].get(
                "success"
            ):
                limitations.append("The selected tool attempt has no successful result")
            else:
                receipt = receipts[spec.step_index]
                if receipt.get("tool") != "cookieai_calculate":
                    limitations.append(
                        "The selected observation is not a calculator result"
                    )
                else:
                    actual = Decimal(receipt["result"]["value"])
                    evidence = {
                        "observed_decimal": str(actual),
                        "event_id": receipt["event_id"],
                    }
                    verdict = (
                        "PASS"
                        if actual.is_finite() and actual == Decimal(spec.expected)
                        else "FAIL"
                    )
        else:
            text = execute_tool("cookieai_read_text", {"path": spec.path}, workspace)[
                "text"
            ]
            evidence = {
                "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "bytes": len(text.encode("utf-8")),
            }
            if spec.kind == "TEXT_EXISTS":
                verdict = "PASS"
            elif spec.kind == "TEXT_SHA256":
                verdict = "PASS" if evidence["sha256"] == spec.expected else "FAIL"
            else:
                actual = json.loads(text)
                verdict = (
                    "PASS"
                    if isinstance(actual, dict)
                    and all(
                        key in actual
                        and type(actual[key]) is type(value)
                        and actual[key] == value
                        for key, value in spec.expected.items()
                    )
                    else "FAIL"
                )
    except FileNotFoundError:
        verdict, limitations = "FAIL", ["The approved artifact is absent"]
    except (
        OSError,
        ValueError,
        InvalidOperation,
        KeyError,
        TypeError,
        RecursionError,
    ) as error:
        limitations.append(type(error).__name__)
    guard()
    return Verification(
        verdict=verdict,
        criterion=spec.kind,
        checked_at=utcnow(),
        evidence=evidence,
        limitations=limitations,
    )
