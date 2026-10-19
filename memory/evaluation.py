"""Ranking metrics over explicit relevance judgments; never invent semantic-quality scores."""

import math


def ranking_metrics(ranked, relevant, k=10):
    ranked = ranked[:k]
    relevant = set(relevant)
    positives = [int(item in relevant) for item in ranked]
    correct = sum(positives)
    reciprocal = next(
        (1 / (index + 1) for index, value in enumerate(positives) if value), 0
    )
    dcg = sum(value / math.log2(index + 2) for index, value in enumerate(positives))
    ideal = sum(1 / math.log2(index + 2) for index in range(min(k, len(relevant))))
    return {
        "precision_at_k": correct / k,
        "recall_at_k": correct / len(relevant) if relevant else 0,
        "mrr": reciprocal,
        "ndcg": dcg / ideal if ideal else 0,
    }
