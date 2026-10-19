"""Exact BM25 and independent candidate fusion for the initial bounded-store deployment."""

import math
import re
from collections import Counter


def terms(text):
    # Conservative English normalization. Keep entity spelling through canonical names.
    irregular = {
        "databases": "database",
        "failures": "failure",
        "failed": "fail",
        "failing": "fail",
        "uses": "use",
        "used": "use",
        "using": "use",
        "choices": "choice",
        "projects": "project",
        "certificates": "certificate",
    }
    return [
        irregular.get(token, token) for token in re.findall(r"\w+", text.casefold())
    ]


def bm25(query, documents, k1=1.5, b=0.75):
    if not documents:
        return []
    counts = [Counter(doc) for doc in documents]
    average = sum(map(len, documents)) / len(documents) or 1
    scores = [0.0] * len(documents)
    for token in set(terms(query)):
        frequency = sum(token in doc for doc in counts)
        idf = math.log(1 + (len(documents) - frequency + 0.5) / (frequency + 0.5))
        for index, doc in enumerate(counts):
            tf = doc[token]
            denominator = tf + k1 * (1 - b + b * len(documents[index]) / average)
            scores[index] += idf * (tf * (k1 + 1) / denominator if denominator else 0)
    maximum = max(scores, default=0)
    return [score / maximum if maximum else 0 for score in scores]


class LocalQueryRewriter:
    """Conservative, deterministic rewrite. Ambiguous references remain unresolved."""

    def rewrite(self, query, recent_messages=()):
        cleaned = re.sub(
            r"\b(what|was|that|we|had|before|please|remember|the|for|did|do|you|know|about)\b",
            " ",
            query,
            flags=re.IGNORECASE,
        )
        cleaned = " ".join(cleaned.split()).strip("?!.")
        return list(dict.fromkeys([query, cleaned or query]))[:4]


def diverse_select(scored, top_k, budget, diversity=0.15, priority_conflicts=False):
    selected = []
    consumed = 0
    remaining = list(scored)
    while remaining and len(selected) < top_k:

        def adjusted(item):
            tokens = set(terms(item[0].canonical_text))
            overlap = max(
                (
                    len(tokens & set(terms(prev[0].canonical_text)))
                    / max(1, len(tokens | set(terms(prev[0].canonical_text))))
                    for prev in selected
                ),
                default=0,
            )
            return (
                item[1]
                - diversity * overlap
                + (
                    2
                    if priority_conflicts and item[0].status.value == "DISPUTED"
                    else 0
                )
            )

        best = max(remaining, key=adjusted)
        remaining.remove(best)
        # UTF-8 byte count is a conservative token upper bound, including non-ASCII.
        cost = len(best[0].model_dump_json().encode("utf-8"))
        if consumed + cost <= budget:
            selected.append(best)
            consumed += cost
    return selected
