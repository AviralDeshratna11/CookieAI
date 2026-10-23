"""Explicit, secret-free model discovery and optional synthetic inference probe.

Never changes .env or the running provider. Reads NEBIUS_API_KEY/NEBIUS_MODEL.
"""

import argparse
import json
import os
from urllib.parse import urlparse

import httpx
from pydantic import SecretStr

from memory.config import Settings
from models.providers import Provider


def discover(base_url, key, *, transport=None):
    parsed = urlparse(base_url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or not parsed.hostname.endswith(".nebius.com")
    ):
        raise ValueError(
            "Use the HTTPS Token Factory endpoint shown in your Nebius console"
        )
    with httpx.Client(
        timeout=30, transport=transport, follow_redirects=False
    ) as client:
        response = client.get(
            base_url.rstrip("/") + "/models", headers={"Authorization": "Bearer " + key}
        )
        response.raise_for_status()
        return [
            row["id"]
            for row in response.json()["data"]
            if isinstance(row.get("id"), str)
            and row["id"].casefold().startswith("nvidia/")
        ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=os.getenv("NEBIUS_MODEL"))
    parser.add_argument(
        "--inference",
        action="store_true",
        help="Make one hosted synthetic request; may consume credits",
    )
    args = parser.parse_args()
    key = os.getenv("NEBIUS_API_KEY")
    if not key:
        raise SystemExit("Set NEBIUS_API_KEY privately. No request was made.")
    base_url = os.getenv("NEBIUS_BASE_URL", "https://api.tokenfactory.nebius.com/v1")
    try:
        models = discover(base_url, key)
        report = {
            "provider": base_url,
            "nvidia_model_ids": models,
            "inference_verified": False,
        }
        if args.inference:
            if not args.model or args.model not in models:
                raise ValueError(
                    "Choose --model exactly from the returned NVIDIA catalog"
                )
            settings = Settings(
                _env_file=None,
                provider_base_url=base_url,
                provider_api_key=SecretStr(key),
                extraction_model=args.model,
            )
            result = Provider(settings).post(
                "/chat/completions",
                {
                    "model": args.model,
                    "messages": [
                        {
                            "role": "user",
                            "content": "Synthetic integration test: respond with the single word READY.",
                        }
                    ],
                    "max_tokens": 32,
                },
            )
            content = result["choices"][0]["message"]["content"]
            report.update(
                model=args.model,
                inference_verified=isinstance(content, str)
                and content.strip() == "READY",
                usage=result.get("usage"),
            )
        print(json.dumps(report, indent=2))
    except httpx.HTTPStatusError as error:
        raise SystemExit(
            f"Nebius returned HTTP {error.response.status_code}; credentials and response body suppressed."
        ) from None
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as error:
        raise SystemExit(
            f"Preflight failed: {type(error).__name__}. Check configuration; no deployment was changed."
        ) from None


if __name__ == "__main__":
    main()
