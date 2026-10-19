"""Fetch only NVIDIA's public pinned tokenizer, never model weights or executable code."""

import hashlib
import json
from pathlib import Path

import httpx

MODEL = "nvidia/NVIDIA-Nemotron-3-Ultra-550B-A55B-BF16"
REVISION = "77df655d5e9f8362164ed14dd8b48f8bce657498"
URL = f"https://huggingface.co/{MODEL}/resolve/{REVISION}/tokenizer.json"


def main():
    destination = Path("config/nemotron-tokenizer.json")
    manifest = Path("config/tokenizer-manifest.json")
    with httpx.Client(follow_redirects=True, timeout=60) as client:
        response = client.get(URL)
        response.raise_for_status()
    if len(response.content) > 32 * 1024 * 1024:
        raise ValueError("tokenizer exceeds download limit")
    digest = hashlib.sha256(response.content).hexdigest()
    if manifest.exists() and json.loads(manifest.read_text())["sha256"] != digest:
        raise ValueError("tokenizer does not match the recorded artifact")
    from tokenizers import Tokenizer

    Tokenizer.from_str(response.text)
    destination.write_bytes(response.content)
    metadata = {
        "model": MODEL,
        "revision": REVISION,
        "url": URL,
        "sha256": digest,
        "bytes": len(response.content),
    }
    manifest.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(json.dumps(metadata))


if __name__ == "__main__":
    main()
