"""Shared anonymized Finary fixtures for normalization tests."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import cast

import pytest

from app.finary_client import (
    FinaryPositionKind,
    FinaryRawAccounts,
    FinaryRawPositionGroup,
    FinaryRawPositions,
)
from app.main import _reset_finary_client_for_tests

_FIXTURE_DIRECTORY = Path(__file__).parent / "fixtures" / "finary"
_LOCAL_DEFAULT_WORKER_COUNT = 2
_CI_MAX_WORKER_COUNT = 4


def _parse_worker_count_override(raw_value: str) -> int:
    try:
        parsed = int(raw_value)
    except ValueError as exc:  # pragma: no cover - defensive path
        raise pytest.UsageError(
            "PYTEST_XDIST_WORKER_COUNT must be a positive integer."
        ) from exc
    if parsed < 1:
        raise pytest.UsageError("PYTEST_XDIST_WORKER_COUNT must be at least 1.")
    return parsed


def _determine_xdist_worker_count(*, env: dict[str, str], cpu_count: int | None) -> int:
    override = env.get("PYTEST_XDIST_WORKER_COUNT")
    if override:
        return _parse_worker_count_override(override)

    if env.get("CI") != "true":
        return _LOCAL_DEFAULT_WORKER_COUNT

    if cpu_count is None or cpu_count < 1:
        return _LOCAL_DEFAULT_WORKER_COUNT

    return min(max(cpu_count - 1, _LOCAL_DEFAULT_WORKER_COUNT), _CI_MAX_WORKER_COUNT)


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


@pytest.fixture(autouse=True)
def isolated_finary_client() -> Iterator[None]:
    """Tests must join their workers before teardown resets the process instance."""

    _reset_finary_client_for_tests()
    try:
        yield
    finally:
        _reset_finary_client_for_tests()


def pytest_xdist_auto_num_workers(config: pytest.Config) -> int:
    del config  # unused, hook signature required by pytest-xdist
    return _determine_xdist_worker_count(env=dict(os.environ), cpu_count=os.cpu_count())
