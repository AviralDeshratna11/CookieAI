import pytest
from tokenizers import Tokenizer, models, pre_tokenizers

from memory.context.budget import ContextBudgetExceeded, TokenCounter, fit


def test_tokenizer_accounting_and_fallback_are_distinguished(tmp_path):
    tokenizer = Tokenizer(models.WordLevel({"[UNK]": 0, "hello": 1}, unk_token="[UNK]"))
    tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
    path = tmp_path / "tokenizer.json"
    tokenizer.save(str(path))
    model = TokenCounter(path)
    fallback = TokenCounter()
    assert model.count("hello hello") == 2
    assert fallback.count("hello hello") == 11
    package = fit(
        {
            "recent_messages": ["hello " * 100 for _ in range(10)],
            "conflicts": [],
            "trust": "untrusted",
        },
        model,
        250,
    )
    assert model.count(package) <= 250
    assert package["context_budget"]["counter"] == "model_tokenizer"
    assert package["recent_messages"]


def test_conflicts_are_never_silently_dropped_to_meet_budget():
    with pytest.raises(ContextBudgetExceeded):
        fit(
            {
                "conflicts": [{"text": "conflicting data" * 1000}],
                "recent_messages": ["optional"],
            },
            TokenCounter(),
            1000,
        )
