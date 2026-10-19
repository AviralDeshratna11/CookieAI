import pytest

from memory.evaluation import ranking_metrics


def test_ranking_metrics():
    result = ranking_metrics(["bad", "good"], ["good"], k=2)
    assert result["precision_at_k"] == 0.5
    assert result["recall_at_k"] == 1
    assert result["mrr"] == 0.5
    assert result["ndcg"] == pytest.approx(0.6309297536)
