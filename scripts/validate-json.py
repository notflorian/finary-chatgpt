#!/usr/bin/env python3
"""Parse the canonical data-only JSON contracts without third-party packages."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JSON_CONTRACTS = (
    ROOT / "docs" / "google-sheets-schema.json",
    ROOT / "docs" / "google-sheets-schema-v2.json",
    ROOT / "finary-bridge" / "app" / "mcp-contract.json",
    ROOT / "n8n" / "workflows" / "finary-mcp-sync.json",
    ROOT / "docs" / "finary-mcp-contract.json",
    *sorted((ROOT / "finary-bridge" / "tests" / "fixtures" / "finary-mcp").glob("*.json")),
    ROOT / "n8n" / "workflows" / "finary-daily-sync.json",
    ROOT / "n8n" / "workflows" / "finary-error-handler.json",
)


def main() -> None:
    for path in JSON_CONTRACTS:
        with path.open(encoding="utf-8") as source:
            json.load(source)
        print(f"valid JSON: {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
