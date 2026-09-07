"""Reject synthetic malformed state at each boundary without upstream authentication."""

import asyncio
import json
import logging
from collections.abc import Iterator
from pathlib import Path
from typing import cast
from unittest.mock import Mock

import pytest
from curl_cffi.requests import Session
from httpx import ASGITransport, AsyncClient, Response
from test_finary_client import _FakeSession
from test_finary_session_store import _store

from app.finary_client import FinaryApiClient, FinaryAuthenticationError, FinaryCredentials
from app.finary_session_store import FinarySessionState, FinarySessionStoreError
from app.main import app

_FIELDS = [("session_id", 512), ("client_cookie", 16_384)]
_INVALID_JSON_VALUES = [
    pytest.param(["synthetic-invalid-marker"], id="nonempty-list"),
    pytest.param({"synthetic-invalid-marker": "synthetic-value"}, id="nonempty-dict"),
    pytest.param([], id="empty-list"),
    pytest.param({}, id="empty-dict"),
    pytest.param(True, id="true"),
    pytest.param(False, id="false"),
    pytest.param(0, id="zero-int"),
    pytest.param(42, id="nonzero-int"),
    pytest.param(0.0, id="zero-float"),
    pytest.param(1.5, id="nonzero-float"),
    pytest.param(None, id="null"),
    pytest.param("", id="empty-string"),
]


def _payload() -> dict[str, object]:
    return {
        "version": 1,
        "session_id": "synthetic-session-marker",
        "client_cookie": "synthetic-cookie-marker",
    }


def _write_payload(path: Path, payload: dict[str, object]) -> None:
    # Write raw JSON: invalid fixtures must never pass through the state constructor.
    with path.open("x", encoding="utf-8") as stream:
        path.chmod(0o600)
        json.dump(payload, stream, indent=2)


def _file_identity(path: Path) -> tuple[bytes, int, int, int]:
    metadata = path.stat()
    return path.read_bytes(), metadata.st_mode, metadata.st_ino, metadata.st_mtime_ns


@pytest.mark.parametrize("field", ["session_id", "client_cookie"])
@pytest.mark.parametrize("value", [*_INVALID_JSON_VALUES, b"synthetic-bytes", ("item",), object()])
def test_state_deliberately_rejects_invalid_fields(field: str, value: object) -> None:
    values = {"session_id": "synthetic-session", "client_cookie": "synthetic-cookie"}
    values[field] = cast(str, value)
    with pytest.raises(ValueError):
        FinarySessionState(**values)


@pytest.mark.parametrize(("field", "limit"), _FIELDS)
def test_state_rejects_oversized_strings(field: str, limit: int) -> None:
    values = {"session_id": "synthetic-session", "client_cookie": "synthetic-cookie"}
    values[field] = "x" * (limit + 1)
    with pytest.raises(ValueError):
        FinarySessionState(**values)


@pytest.mark.parametrize(("field", "limit"), _FIELDS)
@pytest.mark.parametrize("at_limit", [False, True])
def test_state_preserves_exact_strings_and_redacts_repr(
    field: str, limit: int, at_limit: bool
) -> None:
    values = {"session_id": "synthetic-session", "client_cookie": "synthetic-cookie"}
    values[field] = "x" * limit if at_limit else " \tSynthetic-é\n "
    state = FinarySessionState(**values)
    assert state.session_id == values["session_id"]
    assert state.client_cookie == values["client_cookie"]
    assert repr(state) == "FinarySessionState()"


@pytest.mark.parametrize(("field", "limit"), _FIELDS)
@pytest.mark.parametrize(
    "value",
    [
        *_INVALID_JSON_VALUES,
        pytest.param("oversized", id="oversized"),
        pytest.param("missing", id="missing"),
    ],
)
@pytest.mark.parametrize("operation", ["load", "snapshot"])
def test_store_rejects_invalid_persisted_fields_without_mutation(
    tmp_path: Path, field: str, limit: int, value: object, operation: str
) -> None:
    store, path = _store(tmp_path)
    # Establish an existing revision through the public protocol before injecting corruption.
    store.clear()
    payload = _payload()
    if value == "missing":
        del payload[field]
    else:
        payload[field] = "x" * (limit + 1) if value == "oversized" else value
    _write_payload(path, payload)
    lock = path.with_name(path.name + ".lock")
    before, lock_before, directory_mode = (
        _file_identity(path),
        _file_identity(lock),
        path.parent.stat().st_mode,
    )

    for _ in range(2):
        with pytest.raises(
            FinarySessionStoreError,
            match="^Finary session file (is malformed|has unexpected fields)$",
        ):
            getattr(store, operation)()
        assert _file_identity(path) == before
        assert _file_identity(lock) == lock_before
        assert path.parent.stat().st_mode == directory_mode


@pytest.mark.parametrize(("field", "limit"), _FIELDS)
@pytest.mark.parametrize("at_limit", [False, True])
def test_legacy_strings_load_exactly_without_rewriting_and_support_cas(
    tmp_path: Path, field: str, limit: int, at_limit: bool
) -> None:
    store, path = _store(tmp_path)
    payload = _payload()
    payload[field] = "x" * limit if at_limit else " \tSynthetic-é\n "
    _write_payload(path, payload)
    before = _file_identity(path)
    snapshot = store.snapshot()
    assert snapshot.revision == ""
    assert (
        snapshot.state
        == store.load()
        == FinarySessionState(cast(str, payload["session_id"]), cast(str, payload["client_cookie"]))
    )
    assert _file_identity(path) == before
    replacement = FinarySessionState("synthetic-replacement", "synthetic-rotation")
    updated = store.compare_and_swap(snapshot, replacement)
    assert updated is not None and updated.revision != snapshot.revision
    assert store.load() == replacement
    assert store.compare_and_swap(snapshot, snapshot.state) is None
    store.save(snapshot.state)
    assert store.load() == snapshot.state


@pytest.fixture
def guarded_adapter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> Iterator[tuple[FinaryApiClient, Path]]:
    store, path = _store(tmp_path)
    store.clear()
    forbidden = Mock(side_effect=AssertionError("Upstream authentication must not start"))
    # Guard both adapter entry points and fake/real request entry points.
    for method in ("_password_authentication", "_refresh_session", "_post_authentication"):
        monkeypatch.setattr(FinaryApiClient, method, forbidden)
    for transport in (_FakeSession, Session):
        for method in ("get", "post"):
            monkeypatch.setattr(transport, method, forbidden)
    monkeypatch.setattr(Session, "request", forbidden)
    session = _FakeSession()
    factory = Mock(return_value=session)
    adapter = FinaryApiClient(
        FinaryCredentials(
            "synthetic-email-marker", "synthetic-password-marker", "synthetic-mfa-marker"
        ),
        session_factory=factory,
        session_store=store,
        second_factor_code_provider=forbidden,
    )
    monkeypatch.setenv("FINARY_BRIDGE_API_KEY", "synthetic-bridge-key-marker")
    monkeypatch.setattr("app.main.FinaryApiClient.from_environment", lambda: adapter)
    caplog.set_level(logging.DEBUG)
    yield adapter, path
    forbidden.assert_not_called()
    factory.assert_called_once_with()
    assert adapter._session_snapshot is None
    assert adapter._session_state is None
    assert not adapter._authenticated
    assert adapter._token_generation == 0
    for marker in (
        *_payload().values(),
        "synthetic-invalid-marker",
        "synthetic-value",
        "synthetic-email-marker",
        "synthetic-password-marker",
        "synthetic-mfa-marker",
        "synthetic-bridge-key-marker",
        "TypeError",
        "Traceback",
    ):
        if isinstance(marker, str):
            assert marker not in caplog.text
            assert all(marker not in repr(record.__dict__) for record in caplog.records)


@pytest.mark.parametrize("field", ["session_id", "client_cookie"])
@pytest.mark.parametrize("value", _INVALID_JSON_VALUES[:2])
def test_adapter_translates_storage_rejection_before_authentication(
    guarded_adapter: tuple[FinaryApiClient, Path], field: str, value: object
) -> None:
    adapter, path = guarded_adapter
    payload = _payload()
    payload[field] = value
    _write_payload(path, payload)
    for _ in range(2):
        with pytest.raises(FinaryAuthenticationError, match="^Stored Finary session is unusable$"):
            adapter.authenticate()


@pytest.mark.parametrize("endpoint", ["/v1/snapshot", "/v2/snapshot"])
@pytest.mark.parametrize("field", ["session_id", "client_cookie"])
@pytest.mark.parametrize("value", _INVALID_JSON_VALUES[:2])
def test_http_preserves_authentication_envelope_and_malformed_file(
    guarded_adapter: tuple[FinaryApiClient, Path], endpoint: str, field: str, value: object
) -> None:
    _, path = guarded_adapter
    payload = _payload()
    payload[field] = value
    _write_payload(path, payload)
    lock = path.with_name(path.name + ".lock")
    before, lock_before, directory_mode = (
        _file_identity(path),
        _file_identity(lock),
        path.parent.stat().st_mode,
    )

    async def request() -> Response:
        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
        ) as client:
            return await client.get(endpoint, headers={"X-API-Key": "synthetic-bridge-key-marker"})

    for _ in range(2):
        response = asyncio.run(request())
        assert response.status_code == 502
        assert response.headers["content-type"] == "application/json"
        assert response.json() == {
            "error": {
                "code": "FINARY_AUTH_FAILED",
                "message": "Unable to authenticate with Finary",
                "retryable": False,
            }
        }
        assert _file_identity(path) == before
        assert _file_identity(lock) == lock_before
        assert path.parent.stat().st_mode == directory_mode
