"""Model-token accounting with an explicitly labeled conservative fallback."""

import hashlib
import json
from functools import lru_cache
from pathlib import Path


def serialize(value):
    return (
        value
        if isinstance(value, str)
        else json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
    )


@lru_cache(maxsize=4)
def load_tokenizer(path):
    from tokenizers import Tokenizer

    return Tokenizer.from_file(path)


class TokenCounter:
    def __init__(self, path=None):
        self.tokenizer = load_tokenizer(str(Path(path).resolve())) if path else None
        self.mode = "model_tokenizer" if path else "conservative_utf8_upper_bound"
        self.artifact_sha256 = (
            hashlib.sha256(Path(path).read_bytes()).hexdigest() if path else None
        )

    def count(self, value):
        text = serialize(value)
        return (
            len(self.tokenizer.encode(text, add_special_tokens=False).ids)
            if self.tokenizer
            else len(text.encode("utf-8"))
        )


class ContextBudgetExceeded(ValueError):
    pass


def check_prompt(messages, counter, limit, output_tokens, template_reserve, tools=None):
    """Fail before generation; never silently drop conflicts or tool observations.

    The template reserve is explicit because serialized messages cannot measure a
    provider's private chat template. This is an application bound, not a claim
    of exact provider token accounting.
    """
    inputs = counter.count({"messages": messages, "tools": tools or []})
    total = inputs + output_tokens + template_reserve
    if total > limit:
        raise ContextBudgetExceeded("Full assistant prompt and output exceed the limit")
    return {
        "input_tokens": inputs,
        "reserved_output_tokens": output_tokens,
        "template_reserve_tokens": template_reserve,
        "total_reserved_tokens": total,
        "limit": limit,
        "counter": counter.mode,
        "tokenizer_sha256": counter.artifact_sha256,
    }


DEFAULT_ALLOCATION = {
    "recent_messages": 0.25,
    "retrieved_memories": 0.25,
    "autobiographical_state": 0.10,
    "relevant_episodes": 0.10,
    "relevant_experiences": 0.06,
    "relevant_procedures": 0.08,
    "relevant_insights": 0.04,
    "active_goals": 0.04,
    "active_projects": 0.04,
    "prospective_memories": 0.02,
    "other": 0.02,
}


def fit(package, counter, budget, allocation=None):
    allocation = allocation or DEFAULT_ALLOCATION
    # Conflicts are mandatory. A failure is preferable to silently presenting
    # one side of a contradiction as the whole available record.
    arrays = {}
    for key, value in package.items():
        if key in {"conflicts", "uncertainty"}:
            continue
        if isinstance(value, list):
            arrays[key] = [value]
        elif key == "retrieved_memories":
            arrays[key] = [
                items
                for name, items in value.items()
                if isinstance(items, list) and name not in {"conflicts", "uncertainty"}
            ]
    package["context_budget"] = {
        "limit": budget,
        "count": 0,
        "counter": counter.mode,
        "scope": "serialized context JSON, excluding full chat-template overhead",
        "tokenizer_sha256": counter.artifact_sha256,
    }
    while counter.count(package) > max(0, budget - 32):
        candidates = [(key, lists) for key, lists in arrays.items() if any(lists)]
        if not candidates:
            raise ContextBudgetExceeded(
                "Increase context budget or narrow the query to preserve conflicts and metadata"
            )
        key, lists = max(
            candidates,
            key=lambda pair: (
                sum(counter.count(items) for items in pair[1])
                / max(allocation.get(pair[0], allocation.get("other", 0.02)), 0.001)
            ),
        )
        longest = max((items for items in lists if items), key=counter.count)
        longest.pop()
    # Include accounting metadata itself in the bound.
    for _ in range(4):
        package["context_budget"]["count"] = counter.count(package)
    if counter.count(package) > budget:
        raise ContextBudgetExceeded("Context accounting metadata exceeds the budget")
    return package
