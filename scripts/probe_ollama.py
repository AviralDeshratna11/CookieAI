"""Synthetic connectivity probe; does not send stored memories to the model."""

import json

import httpx


def main():
    with httpx.Client(timeout=90) as client:
        response = client.post(
            "http://127.0.0.1:11434/api/chat",
            json={
                "model": "nemotron-3-ultra:cloud",
                "stream": False,
                "think": False,
                "messages": [
                    {
                        "role": "user",
                        "content": 'Return exactly this JSON object and nothing else: {"status":"ready"}',
                    }
                ],
                "options": {"temperature": 0, "num_predict": 128},
            },
        )
        print("HTTP status:", response.status_code)
        data = response.json()
        print(
            json.dumps(
                {
                    key: data[key]
                    for key in ("model", "message", "error")
                    if key in data
                },
                indent=2,
            )[:1800]
        )


if __name__ == "__main__":
    main()
