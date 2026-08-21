"""Explicitly opt-in structural smoke test for the private Finary API."""

import getpass
import json
import os
from collections.abc import Mapping, Sequence

import pytest

from app.finary_client import (
    FinaryApiClient,
    FinaryClientError,
    FinaryFeatureUnavailableError,
    FinaryPositionKind,
)

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.environ.get("FINARY_LIVE_TEST") != "1",
        reason="Set FINARY_LIVE_TEST=1 to run the live Finary smoke test",
    ),
]


def test_live_finary_entities_have_adapter_owned_structure() -> None:
    try:
        client = FinaryApiClient.from_environment(
            second_factor_code_provider=_prompt_second_factor_code
        )
        client.authenticate()
        accounts = client.get_accounts()
        positions = client.get_positions()
    except FinaryClientError as exc:
        pytest.fail(f"{type(exc).__name__}: {exc}", pytrace=False)

    assert isinstance(accounts.records, tuple)
    assert {group.kind for group in positions.groups} == set(FinaryPositionKind)
    assert all(isinstance(group.records, tuple) for group in positions.groups)

    try:
        client.get_liabilities()
    except FinaryFeatureUnavailableError:
        liability_status = "NO VERIFIED COMPLETE SOURCE"
    else:
        liability_status = "COMPLETE SOURCE VERIFIED"

    if os.environ.get("FINARY_LIVE_DESCRIBE") == "1":
        print(
            json.dumps(
                {
                    "accounts": {
                        "record_count": len(accounts.records),
                        "record_shape": _record_shape(accounts.records),
                    },
                    "positions": {
                        group.kind.value: {
                            "record_count": len(group.records),
                            "record_shape": _record_shape(group.records),
                        }
                        for group in positions.groups
                    },
                    "liabilities": {"status": liability_status},
                },
                indent=2,
                sort_keys=True,
            )
        )


def _prompt_second_factor_code(strategy: str) -> str:
    description = "email" if strategy == "email_code" else strategy
    return getpass.getpass(f"Enter the one-time Finary {description} code: ")


def _record_shape(records: Sequence[Mapping[str, object]]) -> dict[str, list[str]]:
    field_types: dict[str, set[str]] = {}
    for record in records:
        for key, value in record.items():
            safe_key = key if isinstance(key, str) else "<non-string-key>"
            field_types.setdefault(safe_key, set()).add(_safe_type_name(value))
    return {key: sorted(types) for key, types in sorted(field_types.items())}


def _safe_type_name(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, str):
        return "string"
    if isinstance(value, int | float):
        return "number"
    if isinstance(value, Mapping):
        return "object"
    if isinstance(value, list):
        item_types = sorted({_safe_type_name(item) for item in value})
        item_summary = "|".join(item_types) if item_types else "empty"
        return f"array[{item_summary}]"
    return "other"
