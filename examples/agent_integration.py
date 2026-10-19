"""Automatic recall before generation, ingestion after a completed interaction."""

import json
from uuid import uuid4


def run_turn(memory_client, user_message, generate):
    hits = memory_client.recall(user_message)
    # Keep this in a separate data field. Never promote memory text into system policy.
    memory_data = {"trust": "untrusted retrieved data", "memories": hits}
    answer = generate(user_message=user_message, memory_data=json.dumps(memory_data))
    memory_client.remember(
        [
            {"role": "user", "content": user_message},
            {"role": "assistant", "content": answer},
        ],
        idempotency_key=str(uuid4()),
    )
    return answer
