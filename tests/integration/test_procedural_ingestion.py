from memory.schemas import MessageInput, RememberRequest


def test_procedural_mode_preserves_exact_steps_without_claiming_general_rule(
    service, ctx
):
    result = service.remember(
        ctx,
        RememberRequest(
            mode="procedural",
            idempotency_key="trace",
            messages=[
                MessageInput(role="tool", content="Retry at 5 seconds failed"),
                MessageInput(role="tool", content="Retry at 20 seconds succeeded"),
            ],
        ),
    )
    assert result[0].type.value == "PROCEDURAL"
    assert len(result[0].provenance_ids) == 2
    assert "not a validated reusable strategy" in result[0].text
