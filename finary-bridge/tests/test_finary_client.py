"""Fixture-based tests for the isolated Finary adapter."""

from __future__ import annotations

import json
import logging
from collections import deque
from collections.abc import Mapping, MutableMapping
from pathlib import Path
from typing import cast

import pytest
from curl_cffi.requests import exceptions as curl_exceptions

from app.finary_client import (
    FinaryApiClient,
    FinaryAuthenticationError,
    FinaryCredentials,
    FinaryFeatureUnavailableError,
    FinaryMalformedResponseError,
    FinaryPositionKind,
    FinaryUpstreamError,
    FinaryUpstreamTimeoutError,
)

_FIXTURE_DIRECTORY = Path(__file__).parent / "fixtures" / "finary"
_SESSION_VALUE = "synthetic-session-value"


class _FakeResponse:
    def __init__(self, payload: object, status_code: int = 200) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> object:
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class _FakeSession:
    def __init__(
        self,
        *,
        post_responses: list[_FakeResponse | Exception] | None = None,
        entity_payloads: Mapping[str, object] | None = None,
        get_error: Exception | None = None,
    ) -> None:
        self.headers: MutableMapping[str, str] = {}
        self.impersonate = ""
        self.post_responses = deque(post_responses or [_FakeResponse(_complete_auth_payload())])
        self.entity_payloads = dict(entity_payloads or {})
        self.get_error = get_error
        self.posted_data: list[Mapping[str, str]] = []
        self.requested_urls: list[str] = []

    def post(
        self,
        url: str,
        *,
        data: Mapping[str, str],
        headers: Mapping[str, str],
        impersonate: str,
        timeout: float,
    ) -> _FakeResponse:
        del url, headers, impersonate, timeout
        self.posted_data.append(dict(data))
        response = self.post_responses.popleft()
        if isinstance(response, Exception):
            raise response
        return response

    def get(self, url: str, *, timeout: float) -> _FakeResponse:
        del timeout
        self.requested_urls.append(url)
        if self.get_error is not None:
            raise self.get_error
        entity_name = url.rsplit("/", maxsplit=1)[-1]
        return _FakeResponse(self.entity_payloads[entity_name])


def _complete_auth_payload() -> dict[str, object]:
    return {
        "response": {"status": "complete"},
        "client": {
            "sessions": [
                {"last_active_token": {"jwt": _SESSION_VALUE}},
            ]
        },
    }


def _credentials(*, mfa_code: str | None = None) -> FinaryCredentials:
    return FinaryCredentials(
        email="person@example.invalid",
        password="synthetic-password",
        mfa_code=mfa_code,
    )


def _load_fixture(name: str) -> dict[str, object]:
    payload = json.loads((_FIXTURE_DIRECTORY / name).read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return cast(dict[str, object], payload)


def _authenticated_client(session: _FakeSession) -> FinaryApiClient:
    client = FinaryApiClient(_credentials(), session_factory=lambda: session)
    client.authenticate()
    return client


def test_successful_authentication_retains_session_in_memory() -> None:
    session = _FakeSession()
    client = FinaryApiClient(_credentials(), session_factory=lambda: session)

    client.authenticate()

    assert session.headers["authorization"] == f"Bearer {_SESSION_VALUE}"
    assert session.impersonate == "chrome110"
    assert session.posted_data == [
        {
            "identifier": "person@example.invalid",
            "password": "synthetic-password",
        }
    ]


def test_authentication_completes_verified_totp_flow() -> None:
    first_factor = {
        "response": {
            "status": "needs_second_factor",
            "id": "sign-in-synthetic-001",
            "supported_second_factors": [{"strategy": "totp"}],
        }
    }
    session = _FakeSession(
        post_responses=[
            _FakeResponse(first_factor),
            _FakeResponse(_complete_auth_payload()),
        ]
    )
    client = FinaryApiClient(
        _credentials(mfa_code="123456"), session_factory=lambda: session
    )

    client.authenticate()

    assert session.posted_data[1] == {"strategy": "totp", "code": "123456"}


def test_authentication_completes_verified_email_code_flow() -> None:
    first_factor = {
        "response": {
            "status": "needs_second_factor",
            "id": "sign-in-synthetic-001",
            "supported_second_factors": [
                {
                    "strategy": "email_code",
                    "email_address_id": "email-synthetic-001",
                    "safe_identifier": "anonymized@example.invalid",
                }
            ],
        }
    }
    prepared_factor = {
        "response": {
            "status": "needs_second_factor",
            "id": "sign-in-synthetic-001",
        }
    }
    session = _FakeSession(
        post_responses=[
            _FakeResponse(first_factor),
            _FakeResponse(prepared_factor),
            _FakeResponse(_complete_auth_payload()),
        ]
    )
    requested_strategies: list[str] = []

    def provide_code(strategy: str) -> str:
        requested_strategies.append(strategy)
        return "654321"

    client = FinaryApiClient(
        _credentials(),
        session_factory=lambda: session,
        second_factor_code_provider=provide_code,
    )

    client.authenticate()

    assert requested_strategies == ["email_code"]
    assert session.posted_data[1] == {
        "strategy": "email_code",
        "email_address_id": "email-synthetic-001",
    }
    assert session.posted_data[2] == {
        "strategy": "email_code",
        "code": "654321",
    }


def test_authentication_failure_is_sanitized() -> None:
    session = _FakeSession(
        post_responses=[
            _FakeResponse(
                {
                    "errors": [
                        {
                            "long_message": "Upstream detail intentionally ignored",
                        }
                    ]
                }
            )
        ]
    )
    client = FinaryApiClient(_credentials(), session_factory=lambda: session)

    with pytest.raises(FinaryAuthenticationError, match="authentication failed"):
        client.authenticate()


def test_missing_mfa_code_maps_to_authentication_failure() -> None:
    session = _FakeSession(
        post_responses=[
            _FakeResponse(
                {
                    "response": {
                        "status": "needs_second_factor",
                        "id": "sign-in-synthetic-001",
                        "supported_second_factors": [
                            {
                                "strategy": "totp",
                                "safe_identifier": "must-not-appear",
                            }
                        ],
                    }
                }
            )
        ]
    )
    client = FinaryApiClient(_credentials(), session_factory=lambda: session)

    with pytest.raises(
        FinaryAuthenticationError,
        match=r"MFA is required.*supported strategies: totp",
    ) as captured:
        client.authenticate()

    assert "must-not-appear" not in str(captured.value)


def test_authentication_timeout_is_translated() -> None:
    session = _FakeSession(
        post_responses=[curl_exceptions.Timeout("synthetic authentication timeout")]
    )
    client = FinaryApiClient(_credentials(), session_factory=lambda: session)

    with pytest.raises(
        FinaryUpstreamTimeoutError, match="authentication request timed out"
    ) as captured:
        client.authenticate()

    assert captured.value.__suppress_context__ is True


def test_structured_logs_exclude_sensitive_values(
    caplog: pytest.LogCaptureFixture,
) -> None:
    session = _FakeSession()
    client = FinaryApiClient(_credentials(), session_factory=lambda: session)

    with caplog.at_level(logging.INFO, logger="app.finary_client"):
        client.authenticate()

    assert {getattr(record, "event", None) for record in caplog.records} == {
        "finary.authentication.started",
        "finary.authentication.succeeded",
    }
    assert "person@example.invalid" not in caplog.text
    assert "synthetic-password" not in caplog.text
    assert _SESSION_VALUE not in caplog.text


def test_account_retrieval_uses_verified_envelope() -> None:
    accounts_payload = _load_fixture("accounts.json")
    session = _FakeSession(entity_payloads={"holdings_accounts": accounts_payload})
    client = _authenticated_client(session)

    accounts = client.get_accounts()

    assert len(accounts.records) == 2
    assert accounts.records[0]["id"] == "account-synthetic-001"
    assert accounts.records[0]["loans"] == []


def test_position_retrieval_covers_verified_asset_collections() -> None:
    positions_payload = _load_fixture("positions.json")
    session = _FakeSession(entity_payloads=positions_payload)
    client = _authenticated_client(session)

    positions = client.get_positions()

    assert {group.kind for group in positions.groups} == set(FinaryPositionKind)
    securities = next(
        group for group in positions.groups if group.kind is FinaryPositionKind.SECURITIES
    )
    assert securities.records[0]["id"] == 1001
    assert securities.records[0]["holdings_account_id"] == "account-synthetic-001"


def test_liability_retrieval_is_explicitly_unavailable() -> None:
    session = _FakeSession()
    client = FinaryApiClient(_credentials(), session_factory=lambda: session)

    with pytest.raises(FinaryFeatureUnavailableError, match="Liability retrieval"):
        client.get_liabilities()

    assert session.requested_urls == []


@pytest.mark.parametrize(
    "payload",
    [
        {"message": "OK", "error": None, "result": {}},
        {"message": "OK", "error": None, "result": ["not-an-object"]},
        {"message": "OK", "result": []},
        ValueError("invalid JSON"),
    ],
)
def test_malformed_account_response_is_rejected(payload: object) -> None:
    session = _FakeSession(entity_payloads={"holdings_accounts": payload})
    client = _authenticated_client(session)

    with pytest.raises(FinaryMalformedResponseError):
        client.get_accounts()


def test_upstream_timeout_is_translated() -> None:
    session = _FakeSession(get_error=curl_exceptions.Timeout("synthetic timeout"))
    client = _authenticated_client(session)

    with pytest.raises(FinaryUpstreamTimeoutError, match="accounts request timed out"):
        client.get_accounts()


def test_upstream_library_error_is_translated() -> None:
    session = _FakeSession(
        get_error=curl_exceptions.RequestException("synthetic transport failure")
    )
    client = _authenticated_client(session)

    with pytest.raises(FinaryUpstreamError, match="accounts request failed"):
        client.get_accounts()
