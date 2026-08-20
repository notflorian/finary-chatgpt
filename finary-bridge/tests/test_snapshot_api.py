"""API tests for the stable normalized snapshot endpoint."""

from __future__ import annotations

import asyncio
from copy import deepcopy

import pytest
from httpx import ASGITransport, AsyncClient, Response

from app.finary_client import (
    FinaryAuthenticationError,
    FinaryFeatureUnavailableError,
    FinaryMalformedResponseError,
    FinaryRawAccounts,
    FinaryRawLiabilities,
    FinaryRawPositions,
    FinaryUpstreamError,
    FinaryUpstreamTimeoutError,
)
from app.main import app, get_finary_client


class _FakeClient:
    def __init__(
        self,
        accounts: FinaryRawAccounts,
        positions: FinaryRawPositions,
        *,
        failure: Exception | None = None,
        liabilities_unavailable: bool = False,
    ) -> None:
        self.accounts = accounts
        self.positions = positions
        self.failure = failure
        self.liabilities_unavailable = liabilities_unavailable
        self.authentication_calls = 0

    def authenticate(self) -> None:
        self.authentication_calls += 1
        if self.failure is not None:
            raise self.failure

    def get_accounts(self) -> FinaryRawAccounts:
        return self.accounts

    def get_positions(self) -> FinaryRawPositions:
        return self.positions

    def get_liabilities(self) -> FinaryRawLiabilities:
        if self.liabilities_unavailable:
            raise FinaryFeatureUnavailableError("synthetic private detail")
        return FinaryRawLiabilities(records=())


def _request(path: str, client: _FakeClient) -> Response:
    async def send_request() -> Response:
        app.dependency_overrides[get_finary_client] = lambda: client
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://testserver"
            ) as http_client:
                return await http_client.get(path)
        finally:
            app.dependency_overrides.clear()

    return asyncio.run(send_request())


def test_snapshot_endpoint_returns_only_stable_schema(
    raw_accounts: FinaryRawAccounts,
    raw_positions: FinaryRawPositions,
) -> None:
    response = _request("/v1/snapshot", _FakeClient(raw_accounts, raw_positions))

    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == "1.0"
    assert payload["reference_currency"] == "EUR"
    assert payload["gross_assets_eur"] == 150.0
    assert payload["liabilities_eur"] == 0.0
    assert payload["net_worth_eur"] == 150.0
    assert len(payload["accounts"]) == 2
    assert len(payload["positions"]) == 6
    assert payload["liabilities"] == []

    serialized = response.text
    for private_field in (
        "holdings_account_id",
        "bank_account",
        "valuable",
        "correlation_id",
        "display_balance",
        "description",
        "loans",
    ):
        assert private_field not in serialized


@pytest.mark.parametrize(
    ("failure", "status_code", "error_code", "retryable"),
    [
        (
            FinaryAuthenticationError("private authentication detail"),
            502,
            "FINARY_AUTH_FAILED",
            False,
        ),
        (
            FinaryUpstreamTimeoutError("private timeout detail"),
            504,
            "FINARY_TIMEOUT",
            True,
        ),
        (
            FinaryMalformedResponseError("private malformed detail"),
            502,
            "FINARY_MALFORMED_RESPONSE",
            False,
        ),
        (
            FinaryUpstreamError("private upstream detail"),
            502,
            "FINARY_UPSTREAM_ERROR",
            True,
        ),
    ],
)
def test_snapshot_endpoint_maps_upstream_errors_without_raw_details(
    failure: Exception,
    status_code: int,
    error_code: str,
    retryable: bool,
    raw_accounts: FinaryRawAccounts,
    raw_positions: FinaryRawPositions,
) -> None:
    response = _request(
        "/v1/snapshot",
        _FakeClient(raw_accounts, raw_positions, failure=failure),
    )

    assert response.status_code == status_code
    assert response.json()["error"]["code"] == error_code
    assert response.json()["error"]["retryable"] is retryable
    assert "private" not in response.text


def test_snapshot_endpoint_maps_unavailable_liabilities_explicitly(
    raw_accounts: FinaryRawAccounts,
    raw_positions: FinaryRawPositions,
) -> None:
    response = _request(
        "/v1/snapshot",
        _FakeClient(raw_accounts, raw_positions, liabilities_unavailable=True),
    )

    assert response.status_code == 503
    assert response.json() == {
        "error": {
            "code": "FINARY_FEATURE_UNAVAILABLE",
            "message": "Required Finary data is unavailable",
            "retryable": False,
        }
    }
    assert "liabilities_eur" not in response.text
    assert "net_worth_eur" not in response.text


def test_snapshot_endpoint_maps_normalization_failure(
    raw_accounts: FinaryRawAccounts,
    raw_positions: FinaryRawPositions,
) -> None:
    records = [deepcopy(dict(record)) for record in raw_accounts.records]
    records[0]["currency"] = {"code": "USD"}
    malformed_accounts = FinaryRawAccounts(records=tuple(records))

    response = _request(
        "/v1/snapshot",
        _FakeClient(malformed_accounts, raw_positions),
    )

    assert response.status_code == 502
    assert response.json() == {
        "error": {
            "code": "SNAPSHOT_VALIDATION_FAILED",
            "message": "Unable to build a valid portfolio snapshot",
            "retryable": False,
        }
    }


def test_health_does_not_create_or_authenticate_finary_client(
    raw_accounts: FinaryRawAccounts,
    raw_positions: FinaryRawPositions,
) -> None:
    client = _FakeClient(raw_accounts, raw_positions)
    response = _request("/health", client)

    assert response.status_code == 200
    assert client.authentication_calls == 0
