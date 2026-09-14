"""Validate the explicit rootful-Linux operator identity without exposing settings."""

import os
import re
import stat
from pathlib import Path


def validate() -> None:
    for suffix, expected in (("UID", os.getuid()), ("GID", os.getgid())):
        value = os.environ.get(f"FINARY_MCP_CANDIDATE_{suffix}", "")
        if not re.fullmatch(r"[1-9][0-9]{0,9}", value) or int(value) != expected:
            raise ValueError("Candidate UID/GID must match the non-root operator identity")
    directory = Path(os.environ["FINARY_MCP_TEST_DIR"])
    info = directory.lstat()
    if (
        not directory.is_absolute()
        or not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.getuid()
        or info.st_gid != os.getgid()
        or stat.S_IMODE(info.st_mode) != 0o700
    ):
        raise ValueError("Candidate state must be an existing private operator-owned directory")


if __name__ == "__main__":
    try:
        validate()
    except (KeyError, OSError, ValueError):
        raise SystemExit("Invalid isolated ownership configuration; see docs/development.md") from None
