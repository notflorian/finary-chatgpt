"""Synthetic regressions for persisted session replacement."""

# Spawn, rather than fork, ensures no inherited Python lock can explain safety.
import fcntl
import multiprocessing
from collections.abc import Iterator
from contextlib import contextmanager
from multiprocessing.connection import Connection
from pathlib import Path

import pytest
from curl_cffi.requests import exceptions as curl_exceptions
from test_finary_client import _credentials, _FakeResponse, _FakeSession, _load_fixture
from test_finary_token_refresh import _Transport, _worker

from app.finary_client import (
    FinaryApiClient,
    FinaryAuthenticationError,
    FinaryMalformedResponseError,
    FinaryUpstreamTimeoutError,
)
from app.finary_session_store import (
    FileFinarySessionStore,
    FinarySessionState,
    FinarySessionStoreError,
)


@pytest.mark.parametrize("status", [401, 403])
def test_cached_rejection_preserves_replacement_and_recovers(tmp_path: Path, status: int) -> None:
    transport = _Transport(tmp_path)
    transport.client.authenticate()
    replacement = FinarySessionState("synthetic-session", "synthetic-cookie-B")
    transport.store.save(replacement)
    transport.now = 45
    transport.replies.append(_FakeResponse({}, status))
    with pytest.raises(FinaryAuthenticationError):
        transport.client.authenticate()
    assert transport.store.load() == replacement
    assert not transport.client._authenticated
    transport.client.authenticate()
    assert transport.client._session_state == replacement
    transport.client.get_accounts()


def test_in_flight_success_cannot_overwrite_replacement(tmp_path: Path) -> None:
    transport = _Transport(tmp_path)
    transport.client.authenticate()
    replacement = FinarySessionState("synthetic-session", "synthetic-cookie-B")
    transport.now = 45
    transport.on_post = lambda: transport.store.save(replacement)
    with pytest.raises(FinaryAuthenticationError):
        transport.client.authenticate()
    assert transport.store.load() == replacement
    assert not transport.client._authenticated
    transport.on_post = lambda: None
    transport.client.authenticate()
    assert transport.client._session_state == replacement


def _bootstrap_client(store: FileFinarySessionStore, **kwargs: object) -> FinaryApiClient:
    session = _FakeSession(
        post_cookie_values=["synthetic-cookie-B"],
        entity_payloads={"holdings_accounts": _load_fixture("accounts.json")},
        **kwargs,
    )
    return FinaryApiClient(_credentials(), session_factory=lambda: session, session_store=store)


def _writer(path: str, operation: str, pipe: Connection) -> None:
    original_flock = fcntl.flock
    reported = False

    def observe(descriptor: int, flags: int) -> None:
        nonlocal reported
        try:
            original_flock(descriptor, flags)
        except BlockingIOError:
            if not reported:
                pipe.send("contended")
                reported = True
            raise

    fcntl.flock = observe
    try:
        store = FileFinarySessionStore(path, lock_timeout_seconds=5)
        if operation == "clear":
            store.clear()
        elif operation == "bootstrap":
            _bootstrap_client(store).bootstrap_session()
        else:
            store.save(FinarySessionState("synthetic-session", "synthetic-cookie-B"))
        pipe.send("done")
    except BaseException as error:
        pipe.send(("failed", type(error).__name__))
    finally:
        pipe.close()


@contextmanager
def _process_writer(path: Path, operation: str) -> Iterator[Connection]:
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe()
    process = context.Process(target=_writer, args=(str(path), operation, child))
    process.start()
    child.close()
    try:
        yield parent
    finally:
        process.join(timeout=6)
        alive = process.is_alive()
        if alive:
            process.terminate()
            process.join(timeout=3)
        parent.close()
        assert not alive, "Store worker did not terminate"
        assert process.exitcode == 0
        process.close()


def _receive(pipe: Connection, expected: str) -> None:
    assert pipe.poll(5), "Store worker did not reach the expected boundary"
    assert pipe.recv() == expected


@pytest.mark.parametrize("operation", ["save", "clear", "bootstrap"])
@pytest.mark.parametrize("outcome", [200, 401, 403])
def test_other_process_replaces_during_refresh(
    tmp_path: Path, operation: str, outcome: int
) -> None:
    transport = _Transport(tmp_path)
    transport.client.authenticate()
    transport.now = 45

    def replace_before_response() -> None:
        with _process_writer(transport.store._path, operation) as pipe:
            _receive(pipe, "done")

    transport.on_post = replace_before_response
    transport.replies.append(_FakeResponse({"jwt": "synthetic-token-old"}, outcome))
    with pytest.raises(FinaryAuthenticationError):
        transport.client.authenticate()
    expected = None if operation == "clear" else FinarySessionState(
        "session-synthetic-001" if operation == "bootstrap" else "synthetic-session",
        "synthetic-cookie-B",
    )
    assert transport.store.load() == expected
    assert not transport.client._authenticated
    assert "authorization" not in transport.client._session.headers
    if expected is not None:
        transport.on_post = lambda: None
        transport.client.authenticate()
        assert transport.client._session_state == expected
        transport.client.get_accounts()


@pytest.mark.parametrize("old_mutation", ["save", "clear"])
@pytest.mark.parametrize("new_mutation", ["save", "clear", "bootstrap"])
def test_comparison_and_mutation_hold_same_cross_process_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, old_mutation: str, new_mutation: str
) -> None:
    from threading import Event

    store = FileFinarySessionStore(tmp_path / "private" / "session.json")
    old = FinarySessionState("synthetic-session", "synthetic-cookie-A")
    store.save(old)
    ticket = store.snapshot()
    compared, release = Event(), Event()
    original = store._snapshot_locked

    def pause_after_read(descriptor: int):
        snapshot = original(descriptor)
        compared.set()
        assert release.wait(5)
        return snapshot

    monkeypatch.setattr(store, "_snapshot_locked", pause_after_read)
    result = []
    with _worker(lambda: result.append(store.compare_and_swap(
        ticket, old if old_mutation == "save" else None
    ))):
        try:
            assert compared.wait(5)
            with _process_writer(store._path, new_mutation) as pipe:
                try:
                    # A real failed flock proves the other process reached the
                    # comparison/mutation boundary, not merely that it started.
                    _receive(pipe, "contended")
                finally:
                    release.set()
                _receive(pipe, "done")
        finally:
            release.set()
    assert result[0] is not None
    monkeypatch.setattr(store, "_snapshot_locked", original)
    state = store.load()
    assert state is None if new_mutation == "clear" else state.client_cookie == "synthetic-cookie-B"


@pytest.mark.parametrize("operation", ["clear", "save", "aba"])
def test_revision_prevents_reuse_of_old_ownership(tmp_path: Path, operation: str) -> None:
    store = FileFinarySessionStore(tmp_path / "private" / "session.json")
    state = FinarySessionState("synthetic-session", "synthetic-cookie-A")
    if operation != "clear":
        store.save(state)
    old = store.snapshot()
    if operation == "clear":
        store.clear()  # Supersedes pending sign-in even if already absent.
    else:
        if operation == "aba":
            store.save(FinarySessionState("synthetic-session", "synthetic-cookie-B"))
        store.save(state)  # Same ID AND cookie is still a new revision.
    assert store.compare_and_swap(old, state) is None
    assert store.snapshot().revision != old.revision


@pytest.mark.parametrize("failure,error", [
    (curl_exceptions.Timeout("synthetic-sensitive"), FinaryUpstreamTimeoutError),
    (_FakeResponse({}), FinaryMalformedResponseError),
])
def test_transient_failure_preserves_replacement_and_recovers(
    tmp_path: Path, failure: object, error: type, caplog: pytest.LogCaptureFixture
) -> None:
    transport = _Transport(tmp_path)
    transport.client.authenticate()
    transport.now = 45
    replacement = FinarySessionState("synthetic-session", "synthetic-cookie-B")
    transport.on_post = lambda: transport.store.save(replacement)
    transport.replies.append(failure)
    with caplog.at_level("INFO"), pytest.raises(error) as caught:
        transport.client.authenticate()
    assert "synthetic-sensitive" not in str(caught.value) + caplog.text
    assert not transport.client._authenticated
    assert "authorization" not in transport.client._session.headers
    assert transport.store.load() == replacement
    transport.on_post = lambda: None
    transport.client.authenticate()
    assert transport.client._session_state == replacement


@pytest.mark.parametrize("failure", ["mfa", "verify", "save"])
def test_bootstrap_failure_preserves_existing_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    store = FileFinarySessionStore(tmp_path / "private" / "session.json")
    old = FinarySessionState("synthetic-session", "synthetic-cookie-A")
    store.save(old)
    kwargs = {}
    if failure == "mfa":
        kwargs["post_responses"] = [_FakeResponse({}, 401)]
    if failure == "verify":
        kwargs["get_error"] = curl_exceptions.Timeout("synthetic-sensitive")
    client = _bootstrap_client(store, **kwargs)
    if failure == "save":
        def fail_replace(*args: object) -> None:
            raise OSError("synthetic-sensitive")
        monkeypatch.setattr("os.replace", fail_replace)
    with pytest.raises((FinaryAuthenticationError, FinaryUpstreamTimeoutError)):
        client.bootstrap_session()
    assert store.load() == old
    assert not client._authenticated
    assert "authorization" not in client._session.headers
    assert not list(store._path.parent.glob(".finary-session-*"))


@pytest.mark.parametrize("status", [401, 403])
def test_rejection_clears_only_unchanged_persisted_revision(tmp_path: Path, status: int) -> None:
    transport = _Transport(tmp_path)
    transport.client.authenticate()
    transport.now = 45
    transport.replies.append(_FakeResponse({}, status))
    with pytest.raises(FinaryAuthenticationError):
        transport.client.authenticate()
    assert transport.store.load() is None
    assert not transport.client._authenticated


@pytest.mark.parametrize("operation", ["save", "clear"])
def test_pending_password_sign_in_cannot_supersede_operator_action(
    tmp_path: Path, operation: str
) -> None:
    store = FileFinarySessionStore(tmp_path / "private" / "session.json")
    client = _bootstrap_client(store)
    original = client._session.post

    def replace_during_sign_in(*args: object, **kwargs: object):
        with _process_writer(store._path, operation) as pipe:
            _receive(pipe, "done")
        return original(*args, **kwargs)

    client._session.post = replace_during_sign_in
    with pytest.raises(FinaryAuthenticationError):
        client.authenticate()
    assert not client._authenticated
    assert "authorization" not in client._session.headers
    assert store.load() == (
        FinarySessionState("synthetic-session", "synthetic-cookie-B")
        if operation == "save" else None
    )


def test_failed_ownership_check_preserves_replacement_and_recovers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    transport = _Transport(tmp_path)
    transport.client.authenticate()
    transport.now = 45
    replacement = FinarySessionState("synthetic-session", "synthetic-cookie-B")

    def fail_check(*args: object):
        transport.store.save(replacement)
        raise FinarySessionStoreError("synthetic-sensitive")

    with monkeypatch.context() as patch, caplog.at_level("INFO"):
        patch.setattr(transport.store, "compare_and_swap", fail_check)
        with pytest.raises(FinaryAuthenticationError) as caught:
            transport.client.authenticate()
    assert "synthetic-sensitive" not in str(caught.value) + caplog.text
    assert transport.store.load() == replacement
    assert not transport.client._authenticated
    assert "authorization" not in transport.client._session.headers
    transport.client.authenticate()
    assert transport.client._session_state == replacement


def test_failed_initial_read_does_not_clear_concurrent_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    transport = _Transport(tmp_path)
    replacement = FinarySessionState("synthetic-session", "synthetic-cookie-B")

    def fail_read():
        transport.store.save(replacement)
        raise FinarySessionStoreError("synthetic-sensitive")

    with monkeypatch.context() as patch:
        patch.setattr(transport.store, "snapshot", fail_read)
        with pytest.raises(FinaryAuthenticationError):
            transport.client.authenticate()
    assert transport.store.load() == replacement
    assert not transport.client._authenticated
    transport.client.authenticate()
    assert transport.client._session_state == replacement


def test_interactive_bootstrap_does_not_lock_out_running_adapter(tmp_path: Path) -> None:
    from threading import Event

    from test_finary_client import _complete_auth_payload

    transport = _Transport(tmp_path)
    transport.client.authenticate()
    waiting, release = Event(), Event()
    session = _FakeSession(
        post_responses=[
            _FakeResponse({"response": {
                "id": "synthetic-sign-in", "status": "needs_second_factor",
                "supported_second_factors": [{"strategy": "totp"}],
            }}),
            _FakeResponse(_complete_auth_payload()),
        ],
        post_cookie_values=[None, "synthetic-cookie-B"],
        entity_payloads={"holdings_accounts": _load_fixture("accounts.json")},
    )

    def provide_code(strategy: str) -> str:
        assert strategy == "totp"
        waiting.set()
        assert release.wait(5)
        return "synthetic-code"

    bootstrap = FinaryApiClient(
        _credentials(), session_factory=lambda: session, session_store=transport.store,
        second_factor_code_provider=provide_code,
    )
    with _worker(bootstrap.bootstrap_session):
        try:
            assert waiting.wait(5)
            transport.now = 45
            transport.client.authenticate()
            transport.client.get_accounts()
            assert transport.store.load().client_cookie == "synthetic-cookie"
        finally:
            release.set()
    assert transport.store.load().client_cookie == "synthetic-cookie-B"
    assert not bootstrap._authenticated


def test_persistence_failure_invalidates_ticket_and_allows_later_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    transport = _Transport(tmp_path)
    transport.client.authenticate()
    transport.now = 45
    before = transport.store.snapshot()

    def fail_replace(*args: object) -> None:
        raise OSError("synthetic-sensitive")

    with monkeypatch.context() as patch:
        patch.setattr("os.replace", fail_replace)
        with pytest.raises(FinaryAuthenticationError):
            transport.client.authenticate()
    after = transport.store.snapshot()
    assert after.state == before.state
    assert after.revision != before.revision
    assert not transport.client._authenticated
    assert "authorization" not in transport.client._session.headers
    assert not list(transport.store._path.parent.glob(".finary-session-*"))
    transport.client.authenticate()
    transport.client.get_accounts()


@pytest.mark.parametrize("mutation", ["save", "clear"])
def test_replacement_at_first_lock_release_detects_split_check_and_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    store = FileFinarySessionStore(tmp_path / "private" / "session.json")
    old = FinarySessionState("synthetic-session", "synthetic-cookie-A")
    store.save(old)
    ticket = store.snapshot()
    original = store._locked
    released = False

    @contextmanager
    def replace_at_release():
        nonlocal released
        with original() as descriptor:
            yield descriptor
        if not released:
            released = True
            # An unsafe snapshot()/save() split releases once after reading:
            # force B into precisely that gap before the stale mutation resumes.
            # With atomic CAS the first release follows the completed mutation.
            with _process_writer(store._path, "save") as pipe:
                _receive(pipe, "done")

    monkeypatch.setattr(store, "_locked", replace_at_release)
    assert store.compare_and_swap(ticket, old if mutation == "save" else None) is not None
    assert released
    assert store.load() == FinarySessionState("synthetic-session", "synthetic-cookie-B")


@pytest.mark.parametrize("document", ["README.md", "docs/operations.md"])
def test_documented_bootstrap_python_verifies_and_publishes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str], document: str,
) -> None:
    repository = Path(__file__).parents[2]
    source = (repository / document).read_text()
    prefix = "docker compose exec -e FINARY_MFA_CODE= finary-bridge python -c '\n"
    python = source.split(prefix, 1)[1].split("\n'", 1)[0]
    store = FileFinarySessionStore(tmp_path / "private" / "session.json")
    store.save(FinarySessionState("synthetic-session", "synthetic-cookie-A"))
    client = _bootstrap_client(store)
    monkeypatch.setattr(FinaryApiClient, "from_environment", lambda **kwargs: client)
    exec(compile(python, document, "exec"), {})
    assert store.load() == FinarySessionState("session-synthetic-001", "synthetic-cookie-B")
    assert capsys.readouterr().out == "Verified session replacement published\n"


def test_busy_store_never_leaves_refreshed_transport_ready(tmp_path: Path) -> None:
    transport = _Transport(tmp_path)
    transport.client.authenticate()
    original = transport.store.load()
    transport.store._lock_timeout_seconds = 0.01
    transport.now = 45
    with transport.store._locked(), pytest.raises(FinaryAuthenticationError):
        transport.client.authenticate()
    assert not transport.client._authenticated
    assert "authorization" not in transport.client._session.headers
    assert transport.store.load() == original
    transport.client.authenticate()
    transport.client.get_accounts()


@pytest.mark.parametrize("status", [200, 401, 403])
@pytest.mark.parametrize("path", ["/v1/snapshot", "/v2/snapshot"])
def test_stale_renewal_has_generic_api_error_and_recovers_with_replacement(
    tmp_path: Path, status: int, path: str, caplog: pytest.LogCaptureFixture
) -> None:
    from test_finary_token_refresh import _api_request

    transport = _Transport(tmp_path)
    transport.client.authenticate()
    transport.now = 45
    replacement = FinarySessionState("synthetic-session-B", "synthetic-cookie-B")
    transport.on_post = lambda: transport.store.save(replacement)
    transport.replies.append(_FakeResponse({"jwt": "synthetic-sensitive-token"}, status))
    with caplog.at_level("INFO"):
        response = _api_request(transport.client, path)
    assert response.status_code == 502
    assert response.json() == {"error": {
        "code": "FINARY_AUTH_FAILED", "message": "Unable to authenticate with Finary",
        "retryable": False,
    }}
    assert transport.store.load() == replacement
    for marker in ("synthetic-session", "synthetic-cookie", "synthetic-sensitive", "password"):
        assert marker not in response.text + caplog.text
    transport.on_post = lambda: None
    assert _api_request(transport.client, "/v2/snapshot").status_code == 200
    assert transport.client._session_state == replacement
