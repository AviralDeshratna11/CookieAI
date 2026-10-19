"""Minimal explicit tools; bearer identity is bound by the service."""

from uuid import uuid4

import httpx


class MemoryClient:
    def __init__(self, base_url, token, session_id=None):
        self.client = httpx.Client(
            base_url=base_url,
            timeout=90,
            headers={
                "Authorization": "Bearer " + token,
                "X-Session-ID": str(session_id or uuid4()),
                "X-Purpose": "agent continuity",
            },
        )

    def remember(self, messages, idempotency_key, mode="infer"):
        response = self.client.post(
            "/v1/memory/remember",
            json={
                "messages": messages,
                "mode": mode,
                "idempotency_key": idempotency_key,
            },
        )
        response.raise_for_status()
        return response.json()

    def recall(self, query, top_k=10):
        response = self.client.post(
            "/v1/memory/search", json={"query": query, "top_k": top_k}
        )
        response.raise_for_status()
        return response.json()

    def forget(self, memory_id):
        response = self.client.delete(f"/v1/memory/{memory_id}")
        response.raise_for_status()

    def close(self):
        self.client.close()
