"""Versioned, fail-closed classification; never converts reasoning to an answer."""

from typing import Literal

from pydantic import BaseModel

VERSION = "strict-native-v2"


class CompletionState(BaseModel):
    state: Literal[
        "final",
        "tool_call",
        "reasoning_only",
        "length_truncated",
        "malformed",
        "refusal",
        "mixed_reasoning_final",
        "incomplete",
    ]
    final: str | None = None
    finish_reason: str | None = None
    adapter_version: str = VERSION


def classify(result):
    try:
        choice = result["choices"][0]
        message = choice["message"]
        finish = choice.get("finish_reason")
        if not isinstance(message, dict):
            raise TypeError
    except (KeyError, TypeError, IndexError, AttributeError):
        return CompletionState(state="malformed")
    if message.get("refusal") or finish == "content_filter":
        return CompletionState(state="refusal", finish_reason=finish)
    if finish == "length":
        return CompletionState(state="length_truncated", finish_reason=finish)
    calls = message.get("tool_calls")
    if calls:
        import json

        try:
            ids = set()
            if finish != "tool_calls" or not isinstance(calls, list):
                raise ValueError
            for call in calls:
                if (
                    call["id"] in ids
                    or not call["id"]
                    or call.get("type") != "function"
                ):
                    raise ValueError
                ids.add(call["id"])
                if not call["function"]["name"] or not isinstance(
                    json.loads(call["function"]["arguments"]), dict
                ):
                    raise ValueError
        except (KeyError, TypeError, ValueError):
            return CompletionState(state="malformed", finish_reason=finish)
        return CompletionState(state="tool_call", finish_reason=finish)
    text = message.get("content")
    if isinstance(text, str) and (
        "<think>" in text.lower() or "</think>" in text.lower()
    ):
        return CompletionState(state="mixed_reasoning_final", finish_reason=finish)
    if finish != "stop":
        return CompletionState(state="incomplete", finish_reason=finish)
    if not isinstance(text, str) or not text.strip():
        return CompletionState(
            state="reasoning_only"
            if message.get("reasoning") or message.get("reasoning_content")
            else "malformed",
            finish_reason=finish,
        )
    return CompletionState(state="final", final=text.strip(), finish_reason=finish)
