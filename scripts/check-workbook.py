"""Validate a complete native Google read offline without printing portfolio values."""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "finary-bridge"))
from app.mcp_consumer import select_native
from app.mcp_workbook import require


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    try:
        result = select_native(json.loads(args.input.read_text()), now=datetime.now(timezone.utc))
        require(result["context"]["run_id"] == args.run_id)
        complete = (
            result["current_complete"]
            and not result["dated_fallback"]
            and not result["stale"]
        )
        print(
            json.dumps(
                {
                    "status": "WORKBOOK_READBACK_VALIDATED"
                    if complete
                    else "WORKBOOK_READBACK_QUALIFIED",
                    "current_complete": result["current_complete"],
                    "dated_fallback": result["dated_fallback"],
                    "stale": result["stale"],
                    "series_break": result["series_break"],
                }
            )
        )
    except (
        ValueError,
        TypeError,
        KeyError,
        IndexError,
        AttributeError,
        OSError,
        RecursionError,
    ):
        raise SystemExit("WORKBOOK_READBACK_REVIEW_REQUIRED") from None


if __name__ == "__main__":
    main()
