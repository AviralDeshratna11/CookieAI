from datetime import datetime, timezone

import pytest

from memory.temporal.resolver import normalize_date


def test_relative_dates_use_conversation_time():
    source = datetime(2026, 10, 19, 10, tzinfo=timezone.utc)
    assert normalize_date("yesterday", source).start.day == 18
    assert normalize_date("next Monday", source).start.day == 26
    summer = normalize_date("last summer", source)
    assert (summer.start.year, summer.start.month, summer.end.month) == (2026, 6, 9)
    with pytest.raises(ValueError):
        normalize_date("some time ago", source)
    with pytest.raises(ValueError):
        normalize_date("today", datetime(2026, 10, 19))
