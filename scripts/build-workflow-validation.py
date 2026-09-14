"""Generate supported MCP artifacts, or fail on drift with --check.

Only current, self-contained contracts participate in artifact generation.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    for builder in (
        "build-mcp-models.py",
        "build-mcp-workbook.py",
        "build-mcp-workflow.py",
    ):
        subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / builder),
                *(["--check"] if args.check else []),
            ],
            check=True,
        )


if __name__ == "__main__":
    main()
