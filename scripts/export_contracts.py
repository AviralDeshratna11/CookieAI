"""Refresh deterministic review artifacts after implementation changes."""

import json
from pathlib import Path

from apps.api.main import create_app
from memory.schemas import Memory


def main():
    Path("docs/openapi.json").write_text(
        json.dumps(create_app().openapi(), indent=2), encoding="utf-8"
    )
    Path("database/schemas/memory.json").write_text(
        json.dumps(Memory.model_json_schema(), indent=2), encoding="utf-8"
    )
    print("Exported OpenAPI and canonical memory schema.")


if __name__ == "__main__":
    main()
