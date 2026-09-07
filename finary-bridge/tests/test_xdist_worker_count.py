"""Tests for xdist worker auto-selection defaults and overrides."""

from __future__ import annotations

import pytest

from tests import conftest


@pytest.mark.parametrize(
    ("env", "cpu_count", "expected"),
    [
        ({}, 16, 2),
        ({"CI": "false"}, 8, 2),
        ({"CI": "true"}, 2, 2),
        ({"CI": "true"}, 4, 3),
        ({"CI": "true"}, 8, 4),
        ({"CI": "true"}, None, 2),
        ({"CI": "true", "PYTEST_XDIST_WORKER_COUNT": "1"}, 8, 1),
        ({"PYTEST_XDIST_WORKER_COUNT": "5"}, 2, 5),
    ],
)
def test_determine_xdist_worker_count(
    env: dict[str, str], cpu_count: int | None, expected: int
) -> None:
    assert conftest._determine_xdist_worker_count(env=env, cpu_count=cpu_count) == expected


@pytest.mark.parametrize("raw_override", ["0", "-2", "invalid"])
def test_determine_xdist_worker_count_rejects_invalid_override(raw_override: str) -> None:
    with pytest.raises(pytest.UsageError):
        conftest._determine_xdist_worker_count(
            env={"PYTEST_XDIST_WORKER_COUNT": raw_override},
            cpu_count=8,
        )
