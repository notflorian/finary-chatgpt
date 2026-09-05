"""API tests for the stable normalized snapshot endpoint."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from copy import deepcopy

import pytest
from httpx import ASGITransport, AsyncClient, Response

import app.main as main_module
from app.finary_client import (
    FinaryAuthenticationError,
    FinaryFeatureUnavailableError,
    FinaryLiabilityCoverage,
    FinaryMalformedResponseError,
    FinaryRawAccounts,
    FinaryRawLiabilities,
    FinaryRawPositions,
    FinaryUpstreamError,
    FinaryUpstreamTimeoutError,
)
from app.main import _reset_finary_client_for_tests, app, get_authenticated_finary_client


class _FakeClient:
    def __init__(
        self,
        accounts: FinaryRawAccounts,
        positions: FinaryRawPositions,
        *,
        failure: Exception | None = None,
        liabilities_unavailable: bool = False,
        liability_coverage: FinaryLiabilityCoverage = FinaryLiabilityCoverage.COMPLETE,
    ) -> None:
        self.accounts = accounts
        self.positions = positions
        self.failure = failure
        self.liabilities_unavailable = liabilities_unavailable
        self.liability_coverage = liability_coverage
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
        return FinaryRawLiabilities(records=(), coverage=self.liability_coverage)


def _request(path: str, client: _FakeClient) -> Response:
    async def send_request() -> Response:
        app.dependency_overrides[get_authenticated_finary_client] = lambda: client
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://testserver"
            ) as http_client:
                return await http_client.get(path)
        finally:
            app.dependency_overrides.clear()

    return asyncio.run(send_request())


def _request_through_bridge_authentication(
    path: str,
    monkeypatch: pytest.MonkeyPatch,
    client_factory: Callable[[], _FakeClient],
    *,
    supplied_key: str | None = None,
) -> Response:
    async def send_request() -> Response:
        monkeypatch.setattr(
            main_module.FinaryApiClient, "from_environment", staticmethod(client_factory)
        )
        headers = {} if supplied_key is None else {"X-API-Key": supplied_key}
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as http_client:
            return await http_client.get(path, headers=headers)

    return asyncio.run(send_request())


def _request_without_override(path: str) -> Response:
    async def send_request() -> Response:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as http_client:
            return await http_client.get(path)

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


def test_snapshot_endpoint_maps_missing_credentials_safely(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_finary_client_for_tests()
    monkeypatch.delenv("FINARY_BRIDGE_API_KEY", raising=False)
    monkeypatch.delenv("FINARY_SESSION_PATH", raising=False)
    monkeypatch.delenv("FINARY_EMAIL", raising=False)
    monkeypatch.delenv("FINARY_PASSWORD", raising=False)
    monkeypatch.delenv("FINARY_MFA_CODE", raising=False)

    response = _request_without_override("/v1/snapshot")

    assert response.status_code == 502
    assert response.json() == {
        "error": {
            "code": "FINARY_AUTH_FAILED",
            "message": "Unable to authenticate with Finary",
            "retryable": False,
        }
    }
    _reset_finary_client_for_tests()


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


@pytest.mark.parametrize(
    "coverage",
    [FinaryLiabilityCoverage.PARTIAL, FinaryLiabilityCoverage.UNAVAILABLE],
)
def test_v2_snapshot_returns_assets_with_null_unknown_liability_totals(
    coverage: FinaryLiabilityCoverage,
    raw_accounts: FinaryRawAccounts,
    raw_positions: FinaryRawPositions,
) -> None:
    response = _request(
        "/v2/snapshot",
        _FakeClient(raw_accounts, raw_positions, liability_coverage=coverage),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == "2.0"
    assert payload["coverage"] == {"liabilities": coverage.value}
    assert payload["gross_assets_eur"] == 150.0
    assert payload["liabilities_eur"] is None
    assert payload["net_worth_eur"] is None
    assert payload["liabilities"] == []


def test_v1_still_rejects_unavailable_coverage_container(
    raw_accounts: FinaryRawAccounts,
    raw_positions: FinaryRawPositions,
) -> None:
    response = _request(
        "/v1/snapshot",
        _FakeClient(
            raw_accounts,
            raw_positions,
            liability_coverage=FinaryLiabilityCoverage.UNAVAILABLE,
        ),
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "FINARY_FEATURE_UNAVAILABLE"


@pytest.mark.parametrize(
    ("failure", "status_code", "error_code"),
    [
        (FinaryAuthenticationError("private"), 502, "FINARY_AUTH_FAILED"),
        (FinaryUpstreamTimeoutError("private"), 504, "FINARY_TIMEOUT"),
        (FinaryMalformedResponseError("private"), 502, "FINARY_MALFORMED_RESPONSE"),
        (FinaryUpstreamError("private"), 502, "FINARY_UPSTREAM_ERROR"),
    ],
)
def test_v2_snapshot_preserves_structured_error_mapping(
    failure: Exception,
    status_code: int,
    error_code: str,
    raw_accounts: FinaryRawAccounts,
    raw_positions: FinaryRawPositions,
) -> None:
    response = _request(
        "/v2/snapshot", _FakeClient(raw_accounts, raw_positions, failure=failure)
    )

    assert response.status_code == status_code
    assert response.json()["error"]["code"] == error_code
    assert "private" not in response.text


@pytest.mark.parametrize("path", ["/v1/snapshot", "/v2/snapshot"])
@pytest.mark.parametrize(
    "supplied_key",
    [
        None,
        "",
        "incorrect-synthetic-key",
        "configured-synthetic-key ",
        "CONFIGURED-SYNTHETIC-KEY",
    ],
)
def test_snapshot_rejects_invalid_bridge_key_before_client_construction(
    path: str,
    supplied_key: str | None,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    expected_key = "configured-synthetic-key"
    factory_calls = 0

    def fail_if_constructed() -> _FakeClient:
        nonlocal factory_calls
        factory_calls += 1
        raise AssertionError("Finary client must not be constructed")

    monkeypatch.setenv("FINARY_BRIDGE_API_KEY", expected_key)
    with caplog.at_level(logging.DEBUG):
        response = _request_through_bridge_authentication(
            path,
            monkeypatch,
            fail_if_constructed,
            supplied_key=supplied_key,
        )

    assert response.status_code == 401
    assert response.json() == {
        "error": {
            "code": "BRIDGE_AUTH_FAILED",
            "message": "Bridge authentication failed",
            "retryable": False,
        }
    }
    assert factory_calls == 0
    for secret_value in (expected_key, supplied_key):
        if secret_value:
            assert secret_value not in response.text
            assert secret_value not in caplog.text


@pytest.mark.parametrize("path", ["/v1/snapshot", "/v2/snapshot"])
def test_snapshot_accepts_correct_bridge_key(
    path: str,
    monkeypatch: pytest.MonkeyPatch,
    raw_accounts: FinaryRawAccounts,
    raw_positions: FinaryRawPositions,
) -> None:
    configured_key = "configured-synthetic-key"
    client = _FakeClient(raw_accounts, raw_positions)
    monkeypatch.setenv("FINARY_BRIDGE_API_KEY", configured_key)

    response = _request_through_bridge_authentication(
        path,
        monkeypatch,
        lambda: client,
        supplied_key=configured_key,
    )

    assert response.status_code == 200
    assert client.authentication_calls == 1


@pytest.mark.parametrize("path", ["/v1/snapshot", "/v2/snapshot"])
@pytest.mark.parametrize("configured_key", [None, ""])
def test_snapshot_allows_no_header_when_bridge_key_is_disabled(
    path: str,
    configured_key: str | None,
    monkeypatch: pytest.MonkeyPatch,
    raw_accounts: FinaryRawAccounts,
    raw_positions: FinaryRawPositions,
) -> None:
    client = _FakeClient(raw_accounts, raw_positions)
    if configured_key is None:
        monkeypatch.delenv("FINARY_BRIDGE_API_KEY", raising=False)
    else:
        monkeypatch.setenv("FINARY_BRIDGE_API_KEY", configured_key)

    response = _request_through_bridge_authentication(
        path,
        monkeypatch,
        lambda: client,
    )

    assert response.status_code == 200
    assert client.authentication_calls == 1


def test_health_remains_public_when_bridge_key_is_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_if_constructed() -> _FakeClient:
        raise AssertionError("Finary client must not be constructed")

    monkeypatch.setenv("FINARY_BRIDGE_API_KEY", "configured-synthetic-key")
    response = _request_through_bridge_authentication(
        "/health",
        monkeypatch,
        fail_if_constructed,
    )

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.parametrize("path", ["/v1/snapshot", "/v2/snapshot"])
def test_snapshot_preserves_finary_error_after_bridge_authentication(
    path: str,
    monkeypatch: pytest.MonkeyPatch,
    raw_accounts: FinaryRawAccounts,
    raw_positions: FinaryRawPositions,
) -> None:
    configured_key = "configured-synthetic-key"
    client = _FakeClient(
        raw_accounts,
        raw_positions,
        failure=FinaryUpstreamTimeoutError("synthetic private detail"),
    )
    monkeypatch.setenv("FINARY_BRIDGE_API_KEY", configured_key)

    response = _request_through_bridge_authentication(
        path,
        monkeypatch,
        lambda: client,
        supplied_key=configured_key,
    )

    assert response.status_code == 504
    assert response.json() == {
        "error": {
            "code": "FINARY_TIMEOUT",
            "message": "Finary request timed out",
            "retryable": True,
        }
    }
    assert "synthetic private detail" not in response.text


@pytest.mark.parametrize("path", ["/v1/snapshot", "/v2/snapshot"])
def test_authorized_construction_failure_is_sanitized_and_next_request_recovers(
    path: str,
    monkeypatch: pytest.MonkeyPatch,
    raw_accounts: FinaryRawAccounts,
    raw_positions: FinaryRawPositions,
) -> None:
    client = _FakeClient(raw_accounts, raw_positions)
    calls = 0

    def construct() -> _FakeClient:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise FinaryAuthenticationError("synthetic private construction detail")
        return client

    monkeypatch.setenv("FINARY_BRIDGE_API_KEY", "configured-synthetic-key")
    response = _request_through_bridge_authentication(
        path, monkeypatch, construct, supplied_key="configured-synthetic-key"
    )
    assert response.status_code == 502
    assert response.json() == {
        "error": {
            "code": "FINARY_AUTH_FAILED",
            "message": "Unable to authenticate with Finary",
            "retryable": False,
        }
    }
    assert main_module._finary_client is None
    assert calls == 1
    for _ in range(2):
        response = _request_through_bridge_authentication(
            path, monkeypatch, construct, supplied_key="configured-synthetic-key"
        )
        assert response.status_code == 200
    assert calls == 2
