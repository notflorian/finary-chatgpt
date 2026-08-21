"""Tests for Phase 3 snapshot orchestration."""

from __future__ import annotations

from datetime import datetime

import pytest

from app.finary_client import (
    FinaryAuthenticationError,
    FinaryFeatureUnavailableError,
    FinaryLiabilityCoverage,
    FinaryRawAccounts,
    FinaryRawLiabilities,
    FinaryRawPositions,
)
from app.normalizer import SnapshotNormalizationError
from app.services.snapshot_service import SnapshotService


class _FakeClient:
    def __init__(
        self,
        accounts: FinaryRawAccounts,
        positions: FinaryRawPositions,
        *,
        liabilities: FinaryRawLiabilities | None = None,
        failure: Exception | None = None,
    ) -> None:
        self.accounts = accounts
        self.positions = positions
        self.liabilities = liabilities or FinaryRawLiabilities(
            records=(), coverage=FinaryLiabilityCoverage.COMPLETE
        )
        self.failure = failure
        self.calls: list[str] = []

    def authenticate(self) -> None:
        self.calls.append("authenticate")
        if self.failure is not None:
            raise self.failure

    def get_accounts(self) -> FinaryRawAccounts:
        self.calls.append("get_accounts")
        return self.accounts

    def get_positions(self) -> FinaryRawPositions:
        self.calls.append("get_positions")
        return self.positions

    def get_liabilities(self) -> FinaryRawLiabilities:
        self.calls.append("get_liabilities")
        return self.liabilities


def test_service_builds_snapshot_from_complete_injected_client(
    raw_accounts: FinaryRawAccounts,
    raw_positions: FinaryRawPositions,
) -> None:
    client = _FakeClient(raw_accounts, raw_positions)
    generated_at = datetime.fromisoformat("2026-08-20T07:30:12+02:00")
    service = SnapshotService(client, clock=lambda: generated_at)

    snapshot = service.get_snapshot()

    assert snapshot.schema_version == "1.0"
    assert snapshot.generated_at == generated_at
    assert snapshot.reference_currency == "EUR"
    assert snapshot.gross_assets_eur == 150.0
    assert snapshot.liabilities_eur == 0.0
    assert snapshot.net_worth_eur == 150.0
    assert len(snapshot.accounts) == 2
    assert len(snapshot.positions) == 6
    assert snapshot.liabilities == ()
    assert client.calls == [
        "authenticate",
        "get_accounts",
        "get_positions",
        "get_liabilities",
    ]


def test_service_propagates_authentication_failure(
    raw_accounts: FinaryRawAccounts,
    raw_positions: FinaryRawPositions,
) -> None:
    client = _FakeClient(
        raw_accounts,
        raw_positions,
        failure=FinaryAuthenticationError("synthetic private detail"),
    )
    with pytest.raises(FinaryAuthenticationError):
        SnapshotService(client).get_snapshot()
    assert client.calls == ["authenticate"]


def test_service_does_not_convert_unavailable_liabilities_to_zero(
    raw_accounts: FinaryRawAccounts,
    raw_positions: FinaryRawPositions,
) -> None:
    class _UnavailableLiabilityClient(_FakeClient):
        def get_liabilities(self) -> FinaryRawLiabilities:
            self.calls.append("get_liabilities")
            raise FinaryFeatureUnavailableError("synthetic unavailable detail")

    client = _UnavailableLiabilityClient(raw_accounts, raw_positions)

    with pytest.raises(FinaryFeatureUnavailableError):
        SnapshotService(client).get_snapshot()


def test_service_does_not_convert_partial_empty_liabilities_to_zero(
    raw_accounts: FinaryRawAccounts,
    raw_positions: FinaryRawPositions,
) -> None:
    client = _FakeClient(
        raw_accounts,
        raw_positions,
        liabilities=FinaryRawLiabilities(
            records=(), coverage=FinaryLiabilityCoverage.PARTIAL
        ),
    )

    with pytest.raises(FinaryFeatureUnavailableError, match="not verified complete"):
        SnapshotService(client).get_snapshot()


def test_service_maps_model_validation_to_normalization_error(
    raw_accounts: FinaryRawAccounts,
    raw_positions: FinaryRawPositions,
) -> None:
    client = _FakeClient(raw_accounts, raw_positions)
    service = SnapshotService(
        client,
        clock=lambda: datetime(2026, 8, 20, 7, 30),
    )

    with pytest.raises(SnapshotNormalizationError, match="model validation"):
        service.get_snapshot()
