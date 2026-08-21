"""Fixture-based tests for the isolated Finary adapter."""

from __future__ import annotations

import json
import logging
from collections import deque
from collections.abc import Mapping, MutableMapping
from dataclasses import fields
from pathlib import Path
from threading import Thread
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
from app.finary_session_store import FileFinarySessionStore, FinarySessionState

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


class _FakeCookies:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str, str], str] = {}

    def get(
        self,
        name: str,
        default: str | None = None,
        domain: str | None = None,
        path: str | None = None,
    ) -> str | None:
        for (stored_name, stored_domain, stored_path), value in self.values.items():
            if (
                stored_name == name
                and (domain is None or stored_domain == domain)
                and (path is None or stored_path == path)
            ):
                return value
        return default

    def set(
        self,
        name: str,
        value: str,
        domain: str = "",
        path: str = "/",
        secure: bool = False,
    ) -> None:
        del secure
        self.values[(name, domain, path)] = value


class _FakeSession:
    def __init__(
        self,
        *,
        post_responses: list[_FakeResponse | Exception] | None = None,
        entity_payloads: Mapping[str, object] | None = None,
        get_error: Exception | None = None,
        post_cookie_values: list[str | None] | None = None,
    ) -> None:
        self.headers: MutableMapping[str, str] = {}
        self.impersonate = ""
        self.cookies = _FakeCookies()
        self.post_responses = deque(post_responses or [_FakeResponse(_complete_auth_payload())])
        self.post_cookie_values = deque(post_cookie_values or [])
        self.entity_payloads = dict(entity_payloads or {})
        self.get_error = get_error
        self.posted_data: list[Mapping[str, str]] = []
        self.posted_urls: list[str] = []
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
        del headers, impersonate, timeout
        self.posted_urls.append(url)
        self.posted_data.append(dict(data))
        response = self.post_responses.popleft()
        if isinstance(response, Exception):
            raise response
        if self.post_cookie_values:
            cookie_value = self.post_cookie_values.popleft()
            if cookie_value is not None:
                self.cookies.set(
                    "__client",
                    cookie_value,
                    domain=".clerk.finary.com",
                    path="/",
                    secure=True,
                )
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
                {
                    "id": "session-synthetic-001",
                    "last_active_token": {"jwt": _SESSION_VALUE},
                },
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
    client = FinaryApiClient(_credentials(mfa_code="123456"), session_factory=lambda: session)

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


def test_wrong_credentials_http_status_is_sanitized() -> None:
    session = _FakeSession(
        post_responses=[
            _FakeResponse(
                {"provider_detail": "must-not-appear"},
                status_code=401,
            )
        ]
    )
    client = FinaryApiClient(_credentials(), session_factory=lambda: session)

    with pytest.raises(
        FinaryAuthenticationError,
        match="rejected the authenticated session",
    ) as captured:
        client.authenticate()

    assert "must-not-appear" not in str(captured.value)


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


def test_backup_code_challenge_cannot_be_bypassed() -> None:
    session = _FakeSession(
        post_responses=[
            _FakeResponse(
                {
                    "response": {
                        "status": "needs_second_factor",
                        "id": "sign-in-synthetic-001",
                        "supported_second_factors": [{"strategy": "backup_code"}],
                    }
                }
            )
        ]
    )
    client = FinaryApiClient(_credentials(), session_factory=lambda: session)

    with pytest.raises(
        FinaryAuthenticationError,
        match=r"MFA is required.*supported strategies: backup_code",
    ):
        client.authenticate()

    assert len(session.posted_data) == 1


def test_mfa_code_is_only_an_explicit_one_time_input() -> None:
    credentials = FinaryCredentials.from_environment(
        {
            "FINARY_EMAIL": "person@example.invalid",
            "FINARY_PASSWORD": "synthetic-password",
            "FINARY_MFA_CODE": "explicit-one-time-value",
        }
    )

    assert credentials.mfa_code == "explicit-one-time-value"
    assert {field.name for field in fields(FinaryCredentials)} == {
        "email",
        "password",
        "mfa_code",
    }


def test_restart_reuses_and_rotates_persisted_session_without_mfa(
    tmp_path: Path,
) -> None:
    private_directory = tmp_path / "session-state"
    private_directory.mkdir(mode=0o700)
    store = FileFinarySessionStore(private_directory / "session.json")
    first_factor = {
        "response": {
            "status": "needs_second_factor",
            "id": "sign-in-synthetic-001",
            "supported_second_factors": [{"strategy": "totp"}],
        }
    }
    bootstrap_session = _FakeSession(
        post_responses=[
            _FakeResponse(first_factor),
            _FakeResponse(_complete_auth_payload()),
        ],
        post_cookie_values=[None, "client-cookie-bootstrap"],
    )
    client_a = FinaryApiClient(
        _credentials(mfa_code="explicit-one-time-value"),
        session_factory=lambda: bootstrap_session,
        session_store=store,
    )

    client_a.authenticate()
    assert store.load() == FinarySessionState(
        session_id="session-synthetic-001",
        client_cookie="client-cookie-bootstrap",
    )

    restart_session = _FakeSession(
        post_responses=[_FakeResponse({"jwt": "synthetic-refreshed-token"})],
        post_cookie_values=["client-cookie-rotated"],
    )
    client_b = FinaryApiClient(
        _credentials(),
        session_factory=lambda: restart_session,
        session_store=store,
    )

    client_b.authenticate()

    assert restart_session.posted_urls == [
        "https://clerk.finary.com/v1/client/sessions/session-synthetic-001/tokens"
    ]
    assert restart_session.headers["authorization"] == ("Bearer synthetic-refreshed-token")
    assert store.load() == FinarySessionState(
        session_id="session-synthetic-001",
        client_cookie="client-cookie-rotated",
    )


def test_rejected_persisted_session_is_cleared(tmp_path: Path) -> None:
    private_directory = tmp_path / "session-state"
    private_directory.mkdir(mode=0o700)
    store = FileFinarySessionStore(private_directory / "session.json")
    store.save(
        FinarySessionState(
            session_id="session-synthetic-revoked",
            client_cookie="client-cookie-revoked",
        )
    )
    session = _FakeSession(
        post_responses=[_FakeResponse({}, status_code=401)],
    )
    client = FinaryApiClient(
        _credentials(),
        session_factory=lambda: session,
        session_store=store,
    )

    with pytest.raises(FinaryAuthenticationError, match="rejected"):
        client.authenticate()

    assert store.load() is None


def test_temporary_refresh_failure_preserves_persisted_session(tmp_path: Path) -> None:
    private_directory = tmp_path / "session-state"
    private_directory.mkdir(mode=0o700)
    store = FileFinarySessionStore(private_directory / "session.json")
    state = FinarySessionState(
        session_id="session-synthetic-temporary-failure",
        client_cookie="client-cookie-temporary-failure",
    )
    store.save(state)
    session = _FakeSession(post_responses=[_FakeResponse({}, status_code=503)])
    client = FinaryApiClient(
        _credentials(),
        session_factory=lambda: session,
        session_store=store,
    )

    with pytest.raises(FinaryUpstreamError, match="unexpected status"):
        client.authenticate()

    assert store.load() == state


def test_session_refresh_logs_exclude_persisted_state(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    private_directory = tmp_path / "session-state"
    private_directory.mkdir(mode=0o700)
    store = FileFinarySessionStore(private_directory / "session.json")
    session_id = "session-sensitive-synthetic-value"
    client_cookie = "cookie-sensitive-synthetic-value"
    store.save(
        FinarySessionState(
            session_id=session_id,
            client_cookie=client_cookie,
        )
    )
    session = _FakeSession(post_responses=[_FakeResponse({"jwt": "jwt-sensitive-synthetic-value"})])
    client = FinaryApiClient(
        _credentials(),
        session_factory=lambda: session,
        session_store=store,
    )

    with caplog.at_level(logging.INFO, logger="app.finary_client"):
        client.authenticate()

    assert "finary.authentication.session_loaded" in {
        getattr(record, "event", None) for record in caplog.records
    }
    assert session_id not in caplog.text
    assert client_cookie not in caplog.text
    assert "jwt-sensitive-synthetic-value" not in caplog.text


def test_malformed_persisted_session_maps_to_authentication_failure(
    tmp_path: Path,
) -> None:
    private_directory = tmp_path / "session-state"
    private_directory.mkdir(mode=0o700)
    session_path = private_directory / "session.json"
    session_path.write_text("not-json", encoding="utf-8")
    session_path.chmod(0o600)
    session = _FakeSession()
    client = FinaryApiClient(
        _credentials(),
        session_factory=lambda: session,
        session_store=FileFinarySessionStore(session_path),
    )

    with pytest.raises(FinaryAuthenticationError, match="unusable"):
        client.authenticate()

    assert session.posted_urls == []
    assert not session_path.exists()


def test_concurrent_authentication_performs_one_session_refresh(
    tmp_path: Path,
) -> None:
    private_directory = tmp_path / "session-state"
    private_directory.mkdir(mode=0o700)
    store = FileFinarySessionStore(private_directory / "session.json")
    store.save(
        FinarySessionState(
            session_id="session-synthetic-concurrent",
            client_cookie="client-cookie-concurrent",
        )
    )
    session = _FakeSession(post_responses=[_FakeResponse({"jwt": "synthetic-refreshed-token"})])
    client = FinaryApiClient(
        _credentials(),
        session_factory=lambda: session,
        session_store=store,
    )
    failures: list[Exception] = []

    def authenticate() -> None:
        try:
            client.authenticate()
        except Exception as exc:  # pragma: no cover - assertion reports details
            failures.append(exc)

    threads = [Thread(target=authenticate) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert failures == []
    assert len(session.posted_urls) == 1


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
