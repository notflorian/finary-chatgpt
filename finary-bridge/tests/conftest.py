"""Shared anonymized Phase 2 fixtures for Phase 3 tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest

from app.finary_client import (
    FinaryPositionKind,
    FinaryRawAccounts,
    FinaryRawPositionGroup,
    FinaryRawPositions,
)

_FIXTURE_DIRECTORY = Path(__file__).parent / "fixtures" / "finary"


def _load_json(name: str) -> dict[str, object]:
    payload = json.loads((_FIXTURE_DIRECTORY / name).read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return cast(dict[str, object], payload)


@pytest.fixture
def raw_accounts() -> FinaryRawAccounts:
    payload = _load_json("accounts.json")
    records = payload["result"]
    assert isinstance(records, list)
    return FinaryRawAccounts(records=tuple(cast(list[dict[str, object]], records)))


@pytest.fixture
def raw_positions() -> FinaryRawPositions:
    payload = _load_json("positions.json")
    groups: list[FinaryRawPositionGroup] = []
    for kind in FinaryPositionKind:
        envelope = payload[kind.value]
        assert isinstance(envelope, dict)
        records = envelope["result"]
        assert isinstance(records, list)
        groups.append(
            FinaryRawPositionGroup(
                kind=kind,
                records=tuple(cast(list[dict[str, object]], records)),
            )
        )
    return FinaryRawPositions(groups=tuple(groups))
