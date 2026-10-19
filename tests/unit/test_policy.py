import pytest
from pydantic import ValidationError

from memory.policy import load_policy


def test_tenant_and_environment_policy_overrides(monkeypatch):
    assert load_policy(tenant={"rolling_messages": 4}).rolling_messages == 4
    monkeypatch.setenv("MEMORY_ROLLING_MESSAGES", "7")
    assert load_policy(tenant={"rolling_messages": 4}).rolling_messages == 7
    with pytest.raises(ValidationError):
        load_policy(tenant={"minimum_support": 0})
