"""Normalize relative dates against conversation time, never machine-local time."""

import calendar
from datetime import datetime, timedelta

from memory.schemas import MemoryCreate, StrictModel


class TimeRange(StrictModel):
    start: datetime
    end: datetime
    precision: str


def normalize_date(expression: str, conversation_time: datetime) -> TimeRange:
    base = MemoryCreate.aware_time(conversation_time)
    day = base.replace(hour=0, minute=0, second=0, microsecond=0)
    value = expression.strip().casefold()
    if value in {"today", "yesterday", "tomorrow"}:
        start = day + timedelta(
            days={"today": 0, "yesterday": -1, "tomorrow": 1}[value]
        )
        return TimeRange(start=start, end=start + timedelta(days=1), precision="DAY")
    if value.startswith("next ") and value[5:] in [
        name.casefold() for name in calendar.day_name
    ]:
        weekday = [name.casefold() for name in calendar.day_name].index(value[5:])
        start = day + timedelta(days=(weekday - day.weekday()) % 7 or 7)
        return TimeRange(start=start, end=start + timedelta(days=1), precision="DAY")
    if value == "last summer":
        year = day.year if day.month >= 9 else day.year - 1
        return TimeRange(
            start=day.replace(year=year, month=6, day=1),
            end=day.replace(year=year, month=9, day=1),
            precision="SEASON_NORTHERN",
        )
    try:
        start = datetime.fromisoformat(expression)
    except ValueError:
        raise ValueError("unsupported or ambiguous date expression") from None
    start = MemoryCreate.aware_time(start)
    return TimeRange(
        start=start, end=start + timedelta(microseconds=1), precision="TIMESTAMP"
    )
