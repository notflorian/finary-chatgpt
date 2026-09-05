"""Credential-free renewal regressions using the real adapter and fake transport."""

import asyncio
from collections import deque
from collections.abc import Callable
from pathlib import Path
from threading import Barrier, Event, Thread

import pytest
from curl_cffi.requests import exceptions as curl_exceptions
from httpx import ASGITransport, AsyncClient, Response
from test_finary_client import _credentials, _FakeResponse, _FakeSession, _load_fixture

from app.finary_client import (
    FinaryApiClient,
    FinaryAuthenticationError,
    FinaryMalformedResponseError,
    FinaryPositionKind,
    FinaryUpstreamError,
    FinaryUpstreamTimeoutError,
)
from app.finary_session_store import FileFinarySessionStore, FinarySessionState
from app.main import app, get_authenticated_finary_client


class _Transport:
    def __init__(self, tmp_path: Path, *, interval: float = 45) -> None:
        self.on_post: Callable[[], None] = lambda: None
        self.on_response: Callable[[_FakeResponse], _FakeResponse] = lambda response: response
        self.now = 0.0
        self.latency = 0.0
        self.issued: dict[str, float] = {}
        self.reads: list[tuple[str, str]] = []
        self.sessions: list[_FakeSession] = []
        self.replies: deque[_FakeResponse | Exception] = deque()
        self.statuses: deque[int] = deque()
        self.payloads = _load_fixture("positions.json")
        self.payloads["holdings_accounts"] = _load_fixture("accounts.json")
        directory = tmp_path / "state"
        directory.mkdir(mode=0o700)
        self.store = FileFinarySessionStore(directory / "session.json")
        self.store.save(FinarySessionState("synthetic-session", "synthetic-cookie"))
        self.client = FinaryApiClient(
            _credentials(),
            session_factory=self.factory,
            session_store=self.store,
            monotonic_clock=lambda: self.now,
            token_refresh_interval_seconds=interval,
        )

    def factory(self) -> _FakeSession:
        transport = self

        class Session(_FakeSession):
            def post(self, url: str, **kwargs: object) -> _FakeResponse:
                assert url.endswith("/tokens")
                self.posted_urls.append(url)
                transport.on_post()
                token = f"synthetic-token-{len(transport.issued)}"
                response = (
                    transport.replies.popleft()
                    if transport.replies
                    else _FakeResponse({"jwt": token})
                )
                if isinstance(response, Exception):
                    raise response
                transport.issued[f"Bearer {token}"] = transport.now
                return response

            def get(self, url: str, *, timeout: float) -> _FakeResponse:
                name = url.rsplit("/", 1)[-1]
                token = self.headers["authorization"]
                transport.reads.append((name, token))
                age = transport.now - transport.issued[token]
                transport.now += transport.latency
                status = (
                    transport.statuses.popleft()
                    if transport.statuses
                    else (401 if age >= 60 else 200)
                )
                return transport.on_response(_FakeResponse(transport.payloads[name], status))

        session = Session()
        self.sessions.append(session)
        return session

    @property
    def refreshes(self) -> int:
        return sum(len(session.posted_urls) for session in self.sessions)


def test_long_collection_refreshes_each_entity(tmp_path: Path) -> None:
    transport = _Transport(tmp_path)
    transport.latency = 10
    transport.client.authenticate()
    transport.client.get_accounts()
    positions = transport.client.get_positions()
    assert len(positions.groups) == 9
    assert [name for name, _ in transport.reads] == [
        "holdings_accounts",
        *(kind.value for kind in FinaryPositionKind),
    ]
    assert [token for _, token in transport.reads] == (
        ["Bearer synthetic-token-0"] * 5 + ["Bearer synthetic-token-1"] * 5
    )
    assert transport.refreshes == 2


@pytest.mark.parametrize("elapsed, refreshes", [(0, 1), (16.999, 1), (17, 2), (18, 2)])
def test_configured_refresh_boundary(tmp_path: Path, elapsed: float, refreshes: int) -> None:
    transport = _Transport(tmp_path, interval=17)
    transport.client.authenticate()
    transport.now = elapsed
    transport.client.get_accounts()
    transport.client.get_positions()
    assert transport.refreshes == refreshes
    assert {token for _, token in transport.reads} == {f"Bearer synthetic-token-{refreshes - 1}"}


def test_entity_renewal_uses_latest_rotated_cookie(tmp_path: Path) -> None:
    transport = _Transport(tmp_path)
    seeded_cookies: list[str | None] = []

    def rotate_cookie() -> None:
        cookies = transport.sessions[-1].cookies
        seeded_cookies.append(cookies.get("__client", domain=".clerk.finary.com", path="/"))
        cookies.set(
            "__client",
            f"synthetic-cookie-{len(seeded_cookies)}",
            domain=".clerk.finary.com",
            path="/",
            secure=True,
        )

    transport.on_post = rotate_cookie
    transport.client.authenticate()
    transport.now = 45
    transport.client.get_accounts()
    transport.statuses.append(401)
    transport.client.get_accounts()
    assert seeded_cookies == ["synthetic-cookie", "synthetic-cookie-1", "synthetic-cookie-2"]
    assert transport.store.load() == FinarySessionState("synthetic-session", "synthetic-cookie-3")
    assert transport.refreshes == 3
    assert len(transport.reads) == 3


@pytest.mark.parametrize("replay_status", [200, 401, 403])
def test_only_failed_collection_is_replayed(tmp_path: Path, replay_status: int) -> None:
    transport = _Transport(tmp_path)
    transport.client.authenticate()
    # A fresh token is rejected mid-collection; a 401 alone does not prove expiry.
    transport.statuses.extend([200, 200, 401, replay_status])
    transport.client.get_accounts()
    if replay_status == 200:
        assert len(transport.client.get_positions().groups) == 9
        assert len(transport.reads) == 11
    else:
        with pytest.raises(FinaryAuthenticationError, match="rejected"):
            transport.client.get_positions()
        assert len(transport.reads) == 4
    assert transport.refreshes == 2
    assert [name for name, _ in transport.reads[:4]] == [
        "holdings_accounts",
        "securities",
        "cryptos",
        "cryptos",
    ]
    assert transport.reads[2][1] != transport.reads[3][1]
    assert transport.store.load() is not None


@pytest.mark.parametrize(
    "status, error", [(403, FinaryAuthenticationError), (503, FinaryUpstreamError)]
)
def test_other_entity_statuses_are_not_replayed(tmp_path: Path, status: int, error: type) -> None:
    transport = _Transport(tmp_path)
    transport.client.authenticate()
    transport.statuses.append(status)
    with pytest.raises(error):
        transport.client.get_accounts()
    assert len(transport.reads) == 1
    assert transport.refreshes == 1
    assert transport.store.load() is not None


_FAILURES = [
    (_FakeResponse({"detail": "synthetic-sensitive"}, 401), FinaryAuthenticationError, True),
    (_FakeResponse({"detail": "synthetic-sensitive"}, 403), FinaryAuthenticationError, True),
    (curl_exceptions.Timeout("synthetic-sensitive"), FinaryUpstreamTimeoutError, False),
    (_FakeResponse({"detail": "synthetic-sensitive"}), FinaryMalformedResponseError, False),
    (_FakeResponse(ValueError("synthetic-sensitive")), FinaryMalformedResponseError, False),
    (_FakeResponse({}, 503), FinaryUpstreamError, False),
    (curl_exceptions.RequestException("synthetic-sensitive"), FinaryUpstreamError, False),
]


@pytest.mark.parametrize(
    "failure, error",
    [
        (curl_exceptions.Timeout("synthetic-sensitive"), FinaryUpstreamTimeoutError),
        (curl_exceptions.RequestException("synthetic-sensitive"), FinaryUpstreamError),
        (_FakeResponse({"detail": "synthetic-sensitive"}), FinaryMalformedResponseError),
        (_FakeResponse({"detail": "synthetic-sensitive"}, 503), FinaryUpstreamError),
    ],
)
def test_failed_replay_is_not_retried(
    tmp_path: Path, failure: _FakeResponse | Exception, error: type
) -> None:
    transport = _Transport(tmp_path)
    transport.client.authenticate()
    transport.statuses.append(401)

    def respond(response: _FakeResponse) -> _FakeResponse:
        if len(transport.reads) == 2:
            if isinstance(failure, Exception):
                raise failure
            return failure
        return response

    transport.on_response = respond
    with pytest.raises(error) as captured:
        transport.client.get_accounts()
    assert "synthetic-sensitive" not in str(captured.value)
    assert transport.refreshes == 2
    assert len(transport.reads) == 2
    assert transport.store.load() is not None


@pytest.mark.parametrize("failure, error, cleared", _FAILURES)
@pytest.mark.parametrize("proactive", [False, True])
def test_refresh_failures_disable_replacement_session(
    tmp_path: Path,
    failure: _FakeResponse | Exception,
    error: type,
    cleared: bool,
    proactive: bool,
    caplog: pytest.LogCaptureFixture,
) -> None:
    transport = _Transport(tmp_path)
    transport.client.authenticate()
    previous_state = transport.store.load()
    transport.replies.append(failure)
    if proactive:
        transport.now = 45
    else:
        transport.statuses.append(401)
    with caplog.at_level("INFO"), pytest.raises(error) as captured:
        transport.client.get_accounts()
    assert "synthetic-sensitive" not in str(captured.value) + caplog.text
    assert transport.refreshes == 2
    assert len(transport.reads) == (0 if proactive else 1)
    assert transport.store.load() == (None if cleared else previous_state)
    assert not transport.client._authenticated
    assert "authorization" not in transport.sessions[-1].headers
    with pytest.raises(FinaryAuthenticationError, match="not authenticated"):
        transport.client.get_accounts()
    assert transport.refreshes == 2


@pytest.mark.parametrize("stale", [False, True])
def test_read_without_renewable_state_never_bootstraps(stale: bool) -> None:
    session = _FakeSession(entity_payloads={"holdings_accounts": _load_fixture("accounts.json")})
    now = [0.0]
    prompts: list[str] = []
    client = FinaryApiClient(
        _credentials(),
        session_factory=lambda: session,
        monotonic_clock=lambda: now[0],
        second_factor_code_provider=lambda strategy: prompts.append(strategy) or "synthetic-code",
    )
    client.authenticate()
    if stale:
        now[0] = 45
    else:
        session.get = lambda *args, **kwargs: _FakeResponse({}, 401)
    with pytest.raises(FinaryAuthenticationError, match="cannot be renewed"):
        client.get_accounts()
    assert len(session.posted_urls) == 1
    assert prompts == []


def _start(action: Callable[[], object]) -> tuple[Thread, list[BaseException]]:
    failures: list[BaseException] = []

    def run() -> None:
        try:
            action()
        except BaseException as error:
            failures.append(error)

    thread = Thread(target=run, daemon=True)
    thread.start()
    return thread, failures


def _finish(worker: tuple[Thread, list[BaseException]]) -> None:
    thread, failures = worker
    thread.join(timeout=5)
    assert not thread.is_alive(), "Synchronization did not terminate"
    assert not failures


def test_concurrent_expiry_refreshes_once(tmp_path: Path) -> None:
    transport = _Transport(tmp_path)
    transport.client.authenticate()
    transport.now = 45
    barrier = Barrier(4)

    def read() -> None:
        barrier.wait(timeout=5)
        transport.client.get_accounts()

    workers = [_start(read) for _ in range(4)]
    for worker in workers:
        _finish(worker)
    assert transport.refreshes == 2
    assert transport.reads == [("holdings_accounts", "Bearer synthetic-token-1")] * 4


def test_replacement_is_not_used_until_refresh_completes(tmp_path: Path) -> None:
    transport = _Transport(tmp_path)
    transport.client.authenticate()
    transport.now = 45
    refreshing, release, attempting = Event(), Event(), Event()
    lock = transport.client._authentication_lock

    class ObservedLock:
        def __enter__(self) -> None:
            attempting.set()
            lock.acquire()

        def __exit__(self, *args: object) -> None:
            lock.release()

    transport.client._authentication_lock = ObservedLock()

    def pause_refresh() -> None:
        refreshing.set()
        assert release.wait(timeout=5)

    transport.on_post = pause_refresh
    first = _start(transport.client.authenticate)
    assert refreshing.wait(timeout=5)
    attempting.clear()
    second = _start(transport.client.get_accounts)
    try:
        assert attempting.wait(timeout=5)
        assert transport.reads == []
        assert "authorization" not in transport.sessions[-1].headers
    finally:
        release.set()
    _finish(first)
    _finish(second)
    assert transport.refreshes == 2
    assert transport.reads == [("holdings_accounts", "Bearer synthetic-token-1")]


def test_late_old_generation_rejection_reuses_new_token(tmp_path: Path) -> None:
    transport = _Transport(tmp_path)
    transport.client.authenticate()
    rejected, release = Event(), Event()

    class LateResponse(_FakeResponse):
        # Delay classification after the GET lock is released, allowing renewal.
        @property
        def status_code(self) -> int:
            rejected.set()
            assert release.wait(timeout=5)
            return 401

        @status_code.setter
        def status_code(self, value: int) -> None:
            pass

    transport.on_response = lambda response: LateResponse({})
    first = _start(transport.client.get_accounts)
    assert rejected.wait(timeout=5)
    transport.on_response = lambda response: response
    transport.now = 45
    second = _start(transport.client.get_accounts)
    try:
        _finish(second)
    finally:
        release.set()
    _finish(first)
    assert transport.refreshes == 2
    assert [token for _, token in transport.reads] == [
        "Bearer synthetic-token-0",
        "Bearer synthetic-token-1",
        "Bearer synthetic-token-1",
    ]
    assert transport.store.load() is not None


def test_concurrent_401_responses_share_one_recovery(tmp_path: Path) -> None:
    transport = _Transport(tmp_path)
    transport.client.authenticate()
    rejected = Barrier(4)

    class ConcurrentResponse(_FakeResponse):
        @property
        def status_code(self) -> int:
            # All four GETs used the same generation before any recovery starts.
            rejected.wait(timeout=5)
            return 401

        @status_code.setter
        def status_code(self, value: int) -> None:
            pass

    def respond(response: _FakeResponse) -> _FakeResponse:
        return ConcurrentResponse({}) if len(transport.reads) <= 4 else response

    transport.on_response = respond
    workers = [_start(transport.client.get_accounts) for _ in range(4)]
    for worker in workers:
        _finish(worker)
    assert transport.refreshes == 2
    assert transport.reads == (
        [("holdings_accounts", "Bearer synthetic-token-0")] * 4
        + [("holdings_accounts", "Bearer synthetic-token-1")] * 4
    )


def test_late_replay_rejection_does_not_disable_new_generation(tmp_path: Path) -> None:
    transport = _Transport(tmp_path)
    transport.client.authenticate()
    transport.statuses.append(401)
    rejected, release = Event(), Event()

    class LateReplay(_FakeResponse):
        @property
        def status_code(self) -> int:
            rejected.set()
            assert release.wait(timeout=5)
            return 401

        @status_code.setter
        def status_code(self, value: int) -> None:
            pass

    def respond(response: _FakeResponse) -> _FakeResponse:
        return LateReplay({}) if len(transport.reads) == 2 else response

    def rejected_read() -> None:
        with pytest.raises(FinaryAuthenticationError, match="rejected"):
            transport.client.get_accounts()

    transport.on_response = respond
    first = _start(rejected_read)
    try:
        assert rejected.wait(timeout=5)
        transport.now = 45
        second = _start(transport.client.get_accounts)
        _finish(second)
    finally:
        release.set()
    _finish(first)
    assert transport.client._authenticated
    assert transport.store.load() is not None
    transport.client.get_accounts()
    assert transport.refreshes == 3
    assert [token for _, token in transport.reads] == [
        "Bearer synthetic-token-0",
        "Bearer synthetic-token-1",
        "Bearer synthetic-token-2",
        "Bearer synthetic-token-2",
    ]


@pytest.mark.parametrize("failure, error, cleared", _FAILURES)
@pytest.mark.parametrize("path", ["/v1/snapshot", "/v2/snapshot"])
def test_real_adapter_refresh_failure_api_envelope(
    tmp_path: Path,
    failure: _FakeResponse | Exception,
    error: type,
    cleared: bool,
    path: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    transport = _Transport(tmp_path)
    transport.client.authenticate()
    transport.statuses.extend([200, 200, 401])
    transport.replies.append(failure)
    expected = {
        FinaryAuthenticationError: (
            502,
            "FINARY_AUTH_FAILED",
            "Unable to authenticate with Finary",
            False,
        ),
        FinaryUpstreamTimeoutError: (504, "FINARY_TIMEOUT", "Finary request timed out", True),
        FinaryMalformedResponseError: (
            502,
            "FINARY_MALFORMED_RESPONSE",
            "Finary returned a malformed response",
            False,
        ),
        FinaryUpstreamError: (
            502,
            "FINARY_UPSTREAM_ERROR",
            "Unable to retrieve data from Finary",
            True,
        ),
    }
    status, code, message, retryable = expected[error]
    with caplog.at_level("INFO"):
        response = _api_request(transport.client, path)
    assert response.status_code == status
    assert response.json() == {"error": {"code": code, "message": message, "retryable": retryable}}
    assert len(transport.reads) == 3
    assert transport.refreshes == 2
    for marker in (
        "synthetic-sensitive",
        "synthetic-token",
        "synthetic-cookie",
        "synthetic-password",
    ):
        assert marker not in response.text + caplog.text


def test_real_adapter_api_recovery_returns_complete_snapshot(tmp_path: Path) -> None:
    transport = _Transport(tmp_path)
    transport.statuses.extend([200, 200, 401, 200])
    response = _api_request(transport.client, "/v2/snapshot")
    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == "2.0"
    assert len(payload["accounts"]) == 2
    assert len(payload["positions"]) == 6
    assert payload["gross_assets_eur"] == 150
    assert payload["coverage"] == {"liabilities": "UNAVAILABLE"}
    assert payload["net_worth_eur"] is None
    assert len(transport.reads) == 11
    assert transport.refreshes == 2


def test_token_expires_between_check_and_response(tmp_path: Path) -> None:
    transport = _Transport(tmp_path)
    transport.client.authenticate()

    def expire_first_response(response: _FakeResponse) -> _FakeResponse:
        if len(transport.reads) == 1:
            transport.now = 60
            response.status_code = 401
        return response

    transport.on_response = expire_first_response
    transport.client.get_accounts()
    assert transport.refreshes == 2
    assert transport.reads == [
        ("holdings_accounts", "Bearer synthetic-token-0"),
        ("holdings_accounts", "Bearer synthetic-token-1"),
    ]


def test_repeated_rejection_disables_access_but_preserves_renewal(tmp_path: Path) -> None:
    transport = _Transport(tmp_path)
    transport.client.authenticate()
    transport.statuses.extend([401, 401])
    with pytest.raises(FinaryAuthenticationError):
        transport.client.get_accounts()
    assert not transport.client._authenticated
    assert "authorization" not in transport.sessions[-1].headers
    assert transport.store.load() is not None
    assert transport.refreshes == 2
    assert len(transport.reads) == 2


def _api_request(client: FinaryApiClient, path: str) -> Response:
    async def request() -> Response:
        app.dependency_overrides[get_authenticated_finary_client] = lambda: client
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://testserver"
            ) as http:
                return await http.get(path)
        finally:
            app.dependency_overrides.clear()

    return asyncio.run(request())


@pytest.mark.parametrize("path", ["/v1/snapshot", "/v2/snapshot"])
@pytest.mark.parametrize(
    "statuses, reads, refreshes", [([200, 401, 401], 3, 2), ([200, 403], 2, 1)]
)
def test_entity_rejection_never_returns_partial_api_snapshot(
    tmp_path: Path,
    path: str,
    statuses: list[int],
    reads: int,
    refreshes: int,
) -> None:
    transport = _Transport(tmp_path)
    transport.statuses.extend(statuses)
    response = _api_request(transport.client, path)
    assert response.status_code == 502
    assert response.json() == {
        "error": {
            "code": "FINARY_AUTH_FAILED",
            "message": "Unable to authenticate with Finary",
            "retryable": False,
        }
    }
    assert len(transport.reads) == reads
    assert transport.refreshes == refreshes
