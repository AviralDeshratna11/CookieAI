from memory.retrieval.hybrid import LocalQueryRewriter, bm25


def test_bm25_rewards_rare_terms_and_normalizes():
    scores = bm25("rare", [["common", "rare"], ["common"], ["common"]])
    assert scores == [1, 0, 0]
    assert bm25("absent", [["common"]]) == [0]
    assert bm25("empty", []) == []


def test_rewriter_preserves_original_without_invented_pronoun_resolution():
    result = LocalQueryRewriter().rewrite("What was the database choice for Alpha?")
    assert result[0] == "What was the database choice for Alpha?"
    assert result[1] == "database choice Alpha"
    assert len(result) <= 4
