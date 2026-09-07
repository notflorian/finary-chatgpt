"""Deterministic memory-only renewal through the real Finary adapter."""

from collections import deque
from collections.abc import Callable
from pathlib import Path
from threading import Event
from unittest.mock import Mock

import pytest
from curl_cffi.requests import exceptions as curl_exceptions
from test_finary_client import (
    _complete_auth_payload,
    _credentials,
    _FakeResponse,
    _FakeSession,
    _load_fixture,
)
from test_finary_token_refresh import _api_request, _observe_lock_contention, _worker

from app.finary_client import (
    FinaryApiClient,
    FinaryAuthenticationError,
    FinaryMalformedResponseError,
    FinaryPositionKind,
    FinaryUpstreamError,
    FinaryUpstreamTimeoutError,
)
from app.finary_session_store import (
    FileFinarySessionStore,
    FinarySessionSnapshot,
    FinarySessionState,
    FinarySessionStore,
    FinarySessionStoreError,
)


@pytest.fixture(autouse=True)
def forbid_file_storage(monkeypatch: pytest.MonkeyPatch):
    forbidden = Mock(side_effect=AssertionError("Memory-only authentication touched file storage"))
    monkeypatch.setattr("app.finary_client.FileFinarySessionStore", forbidden)
    for method in ("snapshot", "load", "save", "clear", "compare_and_swap"):
        monkeypatch.setattr(FileFinarySessionStore, method, forbidden)
    yield
    forbidden.assert_not_called()


class _MemoryTransport:
    def __init__(self, *, mfa: str | None = None) -> None:
        self.now = 0.0
        self.sign_ins = 0
        self.factors = 0
        self.prompts: list[str] = []
        self.seeds: list[str | None] = []
        self.sessions: list[_FakeSession] = []
        self.reads: list[tuple[str, str]] = []
        self.replies: deque[_FakeResponse | Exception] = deque()
        self.statuses: deque[int] = deque()
        self.on_refresh: Callable[[], None] = lambda: None
        self.on_response: Callable[[_FakeResponse], _FakeResponse] = lambda response: response
        self.payloads = _load_fixture("positions.json")
        self.payloads["holdings_accounts"] = _load_fixture("accounts.json")
        self.mfa = mfa
        self.client = FinaryApiClient(
            _credentials(mfa_code="synthetic-mfa-code" if mfa == "code" else None),
            session_factory=self.factory,
            monotonic_clock=lambda: self.now,
            second_factor_code_provider=self.provide_code,
        )

    def provide_code(self, strategy: str) -> str:
        self.prompts.append(strategy)
        assert self.mfa == "provider" and len(self.prompts) == 1, "Unexpected MFA prompt"
        return "synthetic-mfa-code"

    def factory(self) -> _FakeSession:
        transport = self

        class Session(_FakeSession):
            def post(self, url: str, **kwargs: object) -> _FakeResponse:
                self.posted_urls.append(url)
                if url.endswith("/sign_ins"):
                    transport.sign_ins += 1
                    if transport.mfa is not None:
                        return _FakeResponse({"response": {
                            "id": "synthetic-sign-in", "status": "needs_second_factor",
                            "supported_second_factors": [{"strategy": "totp"}],
                        }})
                elif url.endswith("/attempt_second_factor"):
                    transport.factors += 1
                    assert kwargs["data"] == {"strategy": "totp", "code": "synthetic-mfa-code"}
                else:
                    assert url == (
                        "https://clerk.finary.com/v1/client/sessions/session-synthetic-001/tokens"
                    )
                    transport.seeds.append(
                        self.cookies.get("__client", domain=".clerk.finary.com", path="/")
                    )
                    transport.on_refresh()
                    reply = transport.replies.popleft() if transport.replies else _FakeResponse(
                        {"jwt": f"synthetic-token-{transport.refreshes}"}
                    )
                    if isinstance(reply, Exception):
                        raise reply
                    self.cookies.set(
                        "__client", f"synthetic-cookie-{transport.refreshes}",
                        domain=".clerk.finary.com", path="/", secure=True,
                    )
                    return reply
                self.cookies.set(
                    "__client", "synthetic-cookie-0",
                    domain=".clerk.finary.com", path="/", secure=True,
                )
                return _FakeResponse(_complete_auth_payload())

            def get(self, url: str, *, timeout: float) -> _FakeResponse:
                assert transport.client._authenticated
                assert transport.client._token_obtained_at is not None
                assert transport.client._session is self
                name = url.rsplit("/", 1)[-1]
                transport.reads.append((name, self.headers["authorization"]))
                status = transport.statuses.popleft() if transport.statuses else 200
                return transport.on_response(_FakeResponse(transport.payloads[name], status))

        session = Session()
        self.sessions.append(session)
        return session

    @property
    def refreshes(self) -> int:
        return len(self.seeds)

    def assert_single_login(self) -> None:
        assert self.sign_ins == 1
        assert self.factors == (0 if self.mfa is None else 1)
        assert self.prompts == (["totp"] if self.mfa == "provider" else [])


def test_no_store_read_after_expiry_renews_without_bootstrap() -> None:
    transport = _MemoryTransport()
    client = transport.client
    client.authenticate()
    assert len(client.get_accounts().records) == 2
    assert transport.refreshes == 0
    transport.now = 46
    assert len(client.get_accounts().records) == 2
    assert transport.refreshes == 1
    assert transport.seeds == ["synthetic-cookie-0"]
    assert transport.reads == [
        ("holdings_accounts", "Bearer synthetic-session-value"),
        ("holdings_accounts", "Bearer synthetic-token-1"),
    ]
    assert client._session_state == FinarySessionState(
        "session-synthetic-001", "synthetic-cookie-1"
    )
    transport.assert_single_login()


@pytest.mark.parametrize("mfa", [None, "code", "provider"])
def test_explicit_authenticate_renews_from_memory_after_expiry(mfa: str | None) -> None:
    transport = _MemoryTransport(mfa=mfa)
    transport.client.authenticate()
    transport.now = 46
    transport.client.authenticate()
    assert len(transport.client.get_accounts().records) == 2
    assert transport.refreshes == 1
    assert transport.client._mfa_code is None
    transport.assert_single_login()


@pytest.mark.parametrize("session_path", [None, "", "   "])
def test_environment_without_session_path_never_creates_files(
    session_path: str | None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = _MemoryTransport()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("app.finary_client.Session", transport.factory)
    environment = {
        "FINARY_EMAIL": "person@example.invalid", "FINARY_PASSWORD": "synthetic-password",
    }
    if session_path is not None:
        environment["FINARY_SESSION_PATH"] = session_path
    client = FinaryApiClient.from_environment(environment=environment)
    transport.client = client
    client._monotonic_clock = lambda: transport.now
    client.authenticate()
    transport.now = 46
    assert len(client.get_accounts().records) == 2
    assert client._session_store is None
    assert client._session_snapshot is None
    assert list(tmp_path.rglob("*")) == []
    assert transport.refreshes == 1
    transport.assert_single_login()


def test_initial_memory_state_and_fresh_token_are_retained() -> None:
    transport = _MemoryTransport()
    client = transport.client
    client.authenticate()
    assert client._session_state == FinarySessionState(
        "session-synthetic-001", "synthetic-cookie-0"
    )
    for elapsed in (0, 44.999):
        transport.now = elapsed
        client.authenticate()
        assert len(client.get_accounts().records) == 2
    assert client._token_generation == 1
    assert client._token_obtained_at == 0
    assert transport.refreshes == 0
    transport.assert_single_login()


@pytest.mark.parametrize("explicit", [False, True])
def test_successive_refreshes_receive_latest_rotated_cookie(explicit: bool) -> None:
    transport = _MemoryTransport(mfa="provider")
    client = transport.client
    client.authenticate()
    for generation in (1, 2):
        transport.now = 46 * generation
        if explicit:
            client.authenticate()
        assert len(client.get_accounts().records) == 2
        assert client._session_state == FinarySessionState(
            "session-synthetic-001", f"synthetic-cookie-{generation}"
        )
        assert client._token_obtained_at == transport.now
        assert client._token_generation == generation + 1
    assert transport.seeds == ["synthetic-cookie-0", "synthetic-cookie-1"]
    assert len({id(session) for session in transport.sessions}) == 3
    assert [token for _, token in transport.reads] == [
        "Bearer synthetic-token-1", "Bearer synthetic-token-2"
    ]
    transport.assert_single_login()


@pytest.mark.parametrize("statuses, refreshes", [
    ([401, 200], 1), ([401, 401], 1), ([401, 403], 1), ([403], 0),
])
def test_entity_recovery_is_bounded_without_storage(statuses: list[int], refreshes: int) -> None:
    transport = _MemoryTransport(mfa="provider")
    client = transport.client
    client.authenticate()
    transport.statuses.extend(statuses)
    if statuses[-1] == 200:
        assert len(client.get_accounts().records) == 2
    else:
        with pytest.raises(FinaryAuthenticationError, match="rejected"):
            client.get_accounts()
    assert transport.refreshes == refreshes
    assert len(transport.reads) == len(statuses)
    assert [token for _, token in transport.reads] == [
        "Bearer synthetic-session-value", "Bearer synthetic-token-1"
    ][:len(statuses)]
    assert client._session_state == FinarySessionState(
        "session-synthetic-001", f"synthetic-cookie-{refreshes}"
    )
    if statuses[-1] == 401:
        with pytest.raises(FinaryAuthenticationError, match="not authenticated"):
            client.get_accounts()
        assert transport.refreshes == 1
        assert len(transport.reads) == 2
    transport.assert_single_login()


@pytest.mark.parametrize("cookie", [
    None, "", "wrong-name", "wrong-domain", "wrong-path", "oversized",
])
def test_unusable_cookie_preserves_fresh_access_without_inventing_state(cookie: str | None) -> None:
    session = _FakeSession(entity_payloads={"holdings_accounts": _load_fixture("accounts.json")})
    if cookie is not None:
        session.cookies.set(
            "unrelated" if cookie == "wrong-name" else "__client",
            "x" * 16385 if cookie == "oversized" else ("" if cookie == "" else "synthetic-cookie"),
            domain=".example.invalid" if cookie == "wrong-domain" else ".clerk.finary.com",
            path="/other" if cookie == "wrong-path" else "/",
        )
    now = [0.0]
    provider = Mock(side_effect=AssertionError("Unexpected MFA"))
    client = FinaryApiClient(
        _credentials(), session_factory=lambda: session,
        monotonic_clock=lambda: now[0], second_factor_code_provider=provider,
    )
    client.authenticate()
    assert client._session_state is None
    assert len(client.get_accounts().records) == 2
    now[0] = 46
    with pytest.raises(FinaryAuthenticationError, match="cannot be renewed"):
        client.get_accounts()
    assert len(session.posted_urls) == 1
    assert len(session.requested_urls) == 1
    provider.assert_not_called()


@pytest.mark.parametrize("session_id", [None, ""])
def test_missing_session_id_is_never_invented(session_id: str | None) -> None:
    payload = _complete_auth_payload()
    payload["client"]["sessions"][0]["id"] = session_id
    session = _FakeSession(
        post_responses=[_FakeResponse(payload)], post_cookie_values=["synthetic-cookie"],
    )
    client = FinaryApiClient(_credentials(), session_factory=lambda: session)
    with pytest.raises(FinaryMalformedResponseError, match="session identifier"):
        client.authenticate()
    assert client._session_state is None
    assert not client._authenticated
    assert len(session.posted_urls) == 1


_FAILURES = [
    (_FakeResponse({"detail": "synthetic-sensitive"}, 401), FinaryAuthenticationError, True),
    (_FakeResponse({"detail": "synthetic-sensitive"}, 403), FinaryAuthenticationError, True),
    (curl_exceptions.Timeout("synthetic-sensitive"), FinaryUpstreamTimeoutError, False),
    (curl_exceptions.RequestException("synthetic-sensitive"), FinaryUpstreamError, False),
    (_FakeResponse({"detail": "synthetic-sensitive"}, 503), FinaryUpstreamError, False),
    (_FakeResponse({"detail": "synthetic-sensitive"}), FinaryMalformedResponseError, False),
    (_FakeResponse(ValueError("synthetic-sensitive")), FinaryMalformedResponseError, False),
]


def _assert_sanitized(text: str) -> None:
    for marker in (
        "synthetic-sensitive", "synthetic-password", "synthetic-mfa-code",
        "synthetic-cookie", "synthetic-token", "synthetic-session-value",
    ):
        assert marker not in text


@pytest.mark.parametrize("failure, error, rejected", _FAILURES)
@pytest.mark.parametrize("proactive", [False, True])
def test_refresh_failure_disables_access_and_preserves_only_usable_memory_state(
    failure: _FakeResponse | Exception, error: type, rejected: bool, proactive: bool,
    caplog: pytest.LogCaptureFixture,
) -> None:
    transport = _MemoryTransport(mfa="provider")
    client = transport.client
    with caplog.at_level("INFO"):
        client.authenticate()
        previous = client._session_state
        transport.replies.append(failure)
        if proactive:
            transport.now = 46
        else:
            transport.statuses.append(401)
        with pytest.raises(error) as caught:
            client.get_accounts()
        assert not client._authenticated
        assert client._token_obtained_at is None
        assert "authorization" not in client._session.headers
        assert client._session_state == (None if rejected else previous)
        # No automatic entity-login loop, even when the session was rejected.
        for _ in range(2):
            with pytest.raises(FinaryAuthenticationError, match="not authenticated"):
                client.get_accounts()
        assert transport.refreshes == 1
        assert len(transport.reads) == (0 if proactive else 1)
        if not rejected:
            client.authenticate()
            assert len(client.get_accounts().records) == 2
            assert transport.seeds == ["synthetic-cookie-0", "synthetic-cookie-0"]
            assert client._session_state == FinarySessionState(
                "session-synthetic-001", "synthetic-cookie-2"
            )
    transport.assert_single_login()
    _assert_sanitized(str(caught.value) + caplog.text)


@pytest.mark.parametrize("invalid_cookie", ["", "x" * 16385], ids=["missing", "oversized"])
def test_invalid_rotation_is_not_published(invalid_cookie: str) -> None:
    transport = _MemoryTransport()
    client = transport.client
    client.authenticate()
    previous = client._session_state
    transport.now = 46

    class InvalidRotation(_FakeResponse):
        def json(self) -> object:
            client._session.cookies.set(
                "__client", invalid_cookie, domain=".clerk.finary.com", path="/",
            )
            return super().json()

    transport.replies.append(InvalidRotation({"jwt": "synthetic-token-invalid"}))
    with pytest.raises(FinaryAuthenticationError, match="refreshable state"):
        client.get_accounts()
    assert not client._authenticated
    assert "authorization" not in client._session.headers
    assert client._session_state == previous
    assert transport.reads == []
    assert transport.refreshes == 1
    transport.assert_single_login()


@pytest.mark.parametrize("failure", [False, True])
def test_contending_memory_readers_coordinate_one_refresh(failure: bool) -> None:
    transport = _MemoryTransport(mfa="provider")
    client = transport.client
    client.authenticate()
    transport.now = 46
    entered, release = Event(), Event()
    contended = _observe_lock_contention(client)

    def pause() -> None:
        entered.set()
        assert release.wait(timeout=5), "Refresh was not released"

    def first_read() -> None:
        if failure:
            with pytest.raises(FinaryUpstreamTimeoutError):
                client.get_accounts()
        else:
            assert len(client.get_accounts().records) == 2

    def waiting_read() -> None:
        if failure:
            with pytest.raises(FinaryAuthenticationError, match="not authenticated"):
                client.get_accounts()
        else:
            assert len(client.get_accounts().records) == 2

    transport.on_refresh = pause
    if failure:
        transport.replies.append(curl_exceptions.Timeout("synthetic-sensitive"))
    with _worker(first_read):
        try:
            assert entered.wait(timeout=5)
            with _worker(waiting_read):
                try:
                    assert contended.wait(timeout=5)
                    assert transport.reads == []
                    assert not client._authenticated
                    assert client._token_obtained_at is None
                    assert "authorization" not in transport.sessions[-1].headers
                finally:
                    release.set()
        finally:
            release.set()
    assert transport.refreshes == 1
    assert transport.reads == ([] if failure else [
        ("holdings_accounts", "Bearer synthetic-token-1")
    ] * 2)
    if failure:
        transport.on_refresh = lambda: None
        client.authenticate()
        assert len(client.get_accounts().records) == 2
        assert transport.refreshes == 2
    transport.assert_single_login()


@pytest.mark.parametrize("recovery_status", [200, 401, 403])
def test_snapshot_crosses_memory_renewal_boundary_without_partial_results(
    recovery_status: int, caplog: pytest.LogCaptureFixture,
) -> None:
    transport = _MemoryTransport(mfa="provider")

    def advance_after_accounts(response: _FakeResponse) -> _FakeResponse:
        if len(transport.reads) == 1:
            transport.now = 46
        return response

    transport.on_response = advance_after_accounts
    transport.statuses.extend([200, 200, 401, recovery_status])
    with caplog.at_level("INFO"):
        response = _api_request(transport.client, "/v2/snapshot")
    if recovery_status == 200:
        assert response.status_code == 200
        payload = response.json()
        assert payload["schema_version"] == "2.0"
        assert len(payload["accounts"]) == 2
        assert len(payload["positions"]) == 6
        assert payload["gross_assets_eur"] == 150
        assert payload["coverage"] == {"liabilities": "UNAVAILABLE"}
        assert payload["net_worth_eur"] is None
        assert [name for name, _ in transport.reads] == [
            "holdings_accounts", "securities", "cryptos", "cryptos",
            *(kind.value for kind in list(FinaryPositionKind)[2:]),
        ]
    else:
        assert response.status_code == 502
        assert response.json() == {"error": {
            "code": "FINARY_AUTH_FAILED", "message": "Unable to authenticate with Finary",
            "retryable": False,
        }}
        assert len(transport.reads) == 4
    assert transport.seeds == ["synthetic-cookie-0", "synthetic-cookie-1"]
    transport.assert_single_login()
    _assert_sanitized(response.text + caplog.text)


@pytest.mark.parametrize("failure, error, rejected", _FAILURES)
def test_snapshot_refresh_errors_are_sanitized_without_storage(
    failure: _FakeResponse | Exception, error: type, rejected: bool,
    caplog: pytest.LogCaptureFixture,
) -> None:
    transport = _MemoryTransport(mfa="provider")
    transport.statuses.extend([200, 200, 401])
    transport.replies.append(failure)
    expected = {
        FinaryAuthenticationError: (502, "FINARY_AUTH_FAILED", False),
        FinaryUpstreamTimeoutError: (504, "FINARY_TIMEOUT", True),
        FinaryMalformedResponseError: (502, "FINARY_MALFORMED_RESPONSE", False),
        FinaryUpstreamError: (502, "FINARY_UPSTREAM_ERROR", True),
    }
    with caplog.at_level("INFO"):
        response = _api_request(transport.client, "/v2/snapshot")
    status, code, retryable = expected[error]
    assert response.status_code == status
    assert set(response.json()) == {"error"}
    assert response.json()["error"]["code"] == code
    assert response.json()["error"]["retryable"] is retryable
    assert (transport.client._session_state is None) == rejected
    assert len(transport.reads) == 3
    assert transport.refreshes == 1
    transport.assert_single_login()
    _assert_sanitized(response.text + caplog.text)


@pytest.mark.parametrize("outcome", ["success", "failure", "conflict", "missing-cookie"])
def test_configured_storage_must_succeed_before_initial_authentication_is_published(
    outcome: str, caplog: pytest.LogCaptureFixture,
) -> None:
    transport = _MemoryTransport()
    client = transport.client
    state = FinarySessionState("session-synthetic-001", "synthetic-cookie-0")
    store = Mock(spec=FinarySessionStore)
    observed = FinarySessionSnapshot(None, "synthetic-revision-0")
    updated = FinarySessionSnapshot(state, "synthetic-revision-1")
    store.snapshot.return_value = observed
    store.compare_and_swap.return_value = None if outcome == "conflict" else updated
    if outcome == "failure":
        store.compare_and_swap.side_effect = FinarySessionStoreError("synthetic-sensitive")
    if outcome == "missing-cookie":
        client._session = _FakeSession()  # Intentionally no renewable cookie.
    client._session_store = store
    with caplog.at_level("INFO"):
        if outcome == "success":
            client.authenticate()
            assert len(client.get_accounts().records) == 2
            assert client._session_state == state
            assert client._session_snapshot == updated
        else:
            with pytest.raises(FinaryAuthenticationError) as caught:
                client.authenticate()
            _assert_sanitized(str(caught.value))
            assert not client._authenticated
            assert client._token_obtained_at is None
            assert client._session_state is None
            assert client._session_snapshot is None
            assert "authorization" not in client._session.headers
            with pytest.raises(FinaryAuthenticationError, match="not authenticated"):
                client.get_accounts()
            assert transport.reads == []
    store.snapshot.assert_called_once_with()
    if outcome == "missing-cookie":
        store.compare_and_swap.assert_not_called()
    else:
        store.compare_and_swap.assert_called_once_with(observed, state)
        transport.assert_single_login()
    store.save.assert_not_called()
    store.clear.assert_not_called()
    store.load.assert_not_called()
    _assert_sanitized(caplog.text)
