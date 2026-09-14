"""Generate a fresh, PAUSED workbook or a Google spreadsheets.create request offline."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "finary-bridge"))
from app.mcp_workbook import google_create, initialize


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--writer-id", required=True)
    parser.add_argument("--generation", required=True, type=int)
    parser.add_argument("--format", choices=("inventory", "google-create"), default="google-create")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    inventory = initialize(args.writer_id, args.generation)
    payload = google_create(inventory) if args.format == "google-create" else inventory
    # Exclusive creation preserves any earlier artifact or operator edit.
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, ensure_ascii=False)
        stream.write("\n")


if __name__ == "__main__":
    main()
