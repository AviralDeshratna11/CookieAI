from datetime import timedelta

from memory.goals.prospective import (
    ProspectiveFeedback,
    ProspectiveInput,
    ProspectiveService,
)
from memory.schemas import utcnow


def test_reminder_snooze_acknowledge_and_no_repeated_activation(service, ctx):
    prospective = ProspectiveService(service)
    reminder = prospective.create(
        ctx,
        ProspectiveInput(
            trigger_type="CONTEXT",
            trigger={"value": "deploy"},
            action_or_memory="Review the TLS procedure",
        ),
    )
    from uuid import UUID

    identity = UUID(reminder["prospective_id"])
    wake = utcnow() + timedelta(hours=1)
    prospective.feedback(
        ctx, identity, ProspectiveFeedback(status="SNOOZED", snooze_until=wake)
    )
    assert prospective.activate(ctx, {"context": "deploy"}) == []
    matches = prospective.activate(
        ctx, {"context": "deploy"}, now=wake + timedelta(seconds=1)
    )
    assert matches[0]["activation_count"] == 1
    assert (
        prospective.activate(
            ctx, {"context": "deploy"}, now=wake + timedelta(seconds=2)
        )
        == []
    )
    prospective.feedback(
        ctx, identity, ProspectiveFeedback(status="ACKNOWLEDGED", helpful=True)
    )
    assert prospective.list(ctx)[0]["helpful"] is True
