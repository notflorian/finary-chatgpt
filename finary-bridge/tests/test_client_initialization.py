"""Deterministic process-local initialization tests without upstream access."""

import asyncio
from contextlib import ExitStack
from pathlib import Path
from threading import Barrier, Event

import pytest
from httpx import ASGITransport, AsyncClient
from test_finary_token_refresh import _observe_lock_contention, _Transport, _worker
from test_snapshot_api import _FakeClient

import app.main as main
from app.finary_client import (
    FinaryApiClient,
    FinaryAuthenticationError,
    FinaryClient,
    FinaryRawAccounts,
    FinaryRawPositions,
)


def _observe_initialization_contention(monkeypatch: pytest.MonkeyPatch) -> Event:
    contended = Event()
    lock = main._finary_client_lock

    class ObservedLock:
        def __enter__(self) -> None:
            if not lock.acquire(blocking=False):
                # A failed acquisition proves contention at the actual boundary.
                contended.set()
                assert lock.acquire(timeout=5), "Initialization lock acquisition timed out"

        def __exit__(self, *args: object) -> None:
            lock.release()

    monkeypatch.setattr(main, "_finary_client_lock", ObservedLock())
    return contended


@pytest.mark.parametrize("first_fails", [False, True])
def test_cold_initialization_reuse_failure_and_reset(
    monkeypatch: pytest.MonkeyPatch,
    raw_accounts: FinaryRawAccounts,
    raw_positions: FinaryRawPositions,
    first_fails: bool,
) -> None:
    constructing, release = Event(), Event()
    contended = _observe_initialization_contention(monkeypatch)
    constructed: list[FinaryClient] = []
    received: list[FinaryClient] = []
    failure = FinaryAuthenticationError("synthetic construction failure")
    calls = 0

    def construct() -> FinaryClient:
        nonlocal calls
        calls += 1
        candidate = _FakeClient(raw_accounts, raw_positions)
        constructed.append(candidate)
        if calls == 1:
            constructing.set()
            assert release.wait(timeout=5)
            if first_fails:
                raise failure
        return candidate

    def get() -> None:
        received.append(main.get_finary_client())

    def first() -> None:
        if first_fails:
            with pytest.raises(FinaryAuthenticationError) as captured:
                get()
            assert captured.value is failure
        else:
            get()

    monkeypatch.setattr(FinaryApiClient, "from_environment", staticmethod(construct))
    assert calls == 0  # Lazy: installing the factory constructs nothing.
    with ExitStack() as workers:
        try:
            workers.enter_context(_worker(first))
            assert constructing.wait(timeout=5)
            for _ in range(3):
                workers.enter_context(_worker(get))
            assert contended.wait(timeout=5)
            assert calls == 1
            assert received == []
            assert main._finary_client is None
        finally:
            release.set()

    successful = constructed[-1]
    expected_calls = 2 if first_fails else 1
    assert calls == expected_calls
    assert len(received) == (3 if first_fails else 4)
    assert all(client is successful for client in received)
    if first_fails:
        assert all(client is not constructed[0] for client in received)
    assert main.get_finary_client() is successful
    assert main.get_finary_client() is successful
    ready = Barrier(4, timeout=5)

    def get_cached() -> None:
        ready.wait()
        get()

    with ExitStack() as workers:
        for _ in range(4):
            workers.enter_context(_worker(get_cached))
    assert all(client is successful for client in received)
    assert calls == expected_calls

    # Reset only after every worker has joined, then construct a fresh instance.
    main._reset_finary_client_for_tests()
    assert main._finary_client is None
    replacement = main.get_finary_client()
    assert replacement is not successful
    assert replacement is main.get_finary_client()
    assert calls == expected_calls + 1


@pytest.mark.parametrize("expired", [False, True])
def test_getter_clients_share_one_renewal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, expired: bool
) -> None:
    transport = _Transport(tmp_path)
    calls = 0

    def construct() -> FinaryApiClient:
        nonlocal calls
        calls += 1
        return transport.client

    monkeypatch.setattr(FinaryApiClient, "from_environment", staticmethod(construct))
    client = main.get_finary_client()
    if expired:
        client.authenticate()
        transport.now = 45
    baseline = transport.refreshes
    contended = _observe_lock_contention(transport.client)
    renewing, release = Event(), Event()
    received: list[FinaryClient] = []

    def pause_renewal() -> None:
        renewing.set()
        assert release.wait(timeout=5)

    def authenticate() -> None:
        shared = main.get_finary_client()
        received.append(shared)
        shared.authenticate()

    transport.on_post = pause_renewal
    with ExitStack() as workers:
        try:
            workers.enter_context(_worker(authenticate))
            assert renewing.wait(timeout=5)
            workers.enter_context(_worker(authenticate))
            assert contended.wait(timeout=5)
            # Reaching the authentication lock also proves initialization has
            # released its lock before the first caller's renewal completes.
            assert len(received) == 2
            assert all(shared is client for shared in received)
            assert transport.refreshes == baseline + 1
        finally:
            release.set()
    assert calls == 1
    assert transport.refreshes == baseline + 1
    client.authenticate()
    assert transport.refreshes == baseline + 1
    state = transport.store.load()
    main._reset_finary_client_for_tests()
    assert transport.store.load() == state is not None


@pytest.mark.parametrize(
    "path, supplied_key, expected_status",
    [
        ("/health", None, 200),
        ("/v1/snapshot", None, 401),
        ("/v1/snapshot", "wrong-synthetic-key", 401),
        ("/v2/snapshot", None, 401),
        ("/v2/snapshot", "wrong-synthetic-key", 401),
    ],
)
def test_http_completes_without_waiting_for_initialization(
    monkeypatch: pytest.MonkeyPatch,
    raw_accounts: FinaryRawAccounts,
    raw_positions: FinaryRawPositions,
    path: str,
    supplied_key: str | None,
    expected_status: int,
) -> None:
    constructing, release, completed = Event(), Event(), Event()
    contended = _observe_initialization_contention(monkeypatch)
    calls = 0

    def construct() -> FinaryClient:
        nonlocal calls
        calls += 1
        constructing.set()
        assert release.wait(timeout=5)
        return _FakeClient(raw_accounts, raw_positions)

    async def request() -> None:
        headers = {} if supplied_key is None else {"X-API-Key": supplied_key}
        async with AsyncClient(
            transport=ASGITransport(app=main.app), base_url="http://testserver"
        ) as http:
            response = await http.get(path, headers=headers)
        assert response.status_code == expected_status
        if expected_status == 401:
            assert response.json()["error"]["code"] == "BRIDGE_AUTH_FAILED"
        completed.set()

    monkeypatch.setenv("FINARY_BRIDGE_API_KEY", "configured-synthetic-key")
    monkeypatch.setattr(FinaryApiClient, "from_environment", staticmethod(construct))
    with ExitStack() as workers:
        try:
            workers.enter_context(_worker(main.get_finary_client))
            assert constructing.wait(timeout=5)
            workers.enter_context(_worker(lambda: asyncio.run(request())))
            assert completed.wait(timeout=3), "HTTP request waited for initialization"
            assert not contended.is_set()
            assert calls == 1
            assert main._finary_client is None
        finally:
            release.set()
