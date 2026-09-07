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
from app.finary_session_store import (
    _MAX_FILE_BYTES,
    FileFinarySessionStore,
    FinarySessionState,
    FinarySessionStoreError,
)
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


def _file_identity(path: Path) -> tuple[bytes, int, int, int, int, int, int]:
    metadata = path.stat()
    return (
        path.read_bytes(), metadata.st_mode, metadata.st_ino, metadata.st_mtime_ns,
        metadata.st_ctime_ns, metadata.st_uid, metadata.st_gid,
    )


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
        "ValueError",
        "RecursionError",
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


@pytest.mark.parametrize(
    ("version_json", "decoder_error"),
    [
        pytest.param("9" * 5_000, ValueError, id="oversized-integer"),
        pytest.param("[" * 12_000 + "0" + "]" * 12_000, RecursionError, id="deep-array"),
    ],
)
@pytest.mark.parametrize(
    "boundary", ["load", "snapshot", "adapter", "/v1/snapshot", "/v2/snapshot"]
)
def test_json_decoding_failure_is_sanitized_and_preserves_state(
    guarded_adapter: tuple[FinaryApiClient, Path],
    caplog: pytest.LogCaptureFixture,
    version_json: str,
    decoder_error: type[Exception],
    boundary: str,
) -> None:
    adapter, path = guarded_adapter
    # Build raw tokens without integer conversion or recursive serialization.
    _write_version_json(path, version_json)
    raw = path.read_bytes()
    assert len(raw) <= _MAX_FILE_BYTES
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.parent.stat().st_mode & 0o777 == 0o700
    # Observe decoder behavior without assuming a version-specific nesting threshold.
    storage_message = "Finary session file is malformed"
    decoder_message = None
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except (ValueError, RecursionError) as error:
        assert type(error) is decoder_error  # Excludes ordinary JSONDecodeError.
        decoder_message = str(error)
    else:
        assert decoder_error is RecursionError  # Oversized integers must still fail.
        version = decoded.pop("version")
        for _ in range(12_000):
            assert type(version) is list and len(version) == 1
            version = version[0]
        assert type(version) is int and version == 0
        assert decoded == {key: value for key, value in _payload().items() if key != "version"}
        storage_message = "Finary session file version is unsupported"
    _assert_decoding_rejection(
        adapter, path, caplog, boundary, storage_message, decoder_message
    )
    _assert_explicit_recovery(path)


@pytest.mark.parametrize("decoder_error", [ValueError, RecursionError])
@pytest.mark.parametrize(
    "boundary", ["load", "snapshot", "adapter", "/v1/snapshot", "/v2/snapshot"]
)
def test_injected_json_decoding_failure_is_sanitized_and_preserves_state(
    guarded_adapter: tuple[FinaryApiClient, Path],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    decoder_error: type[Exception],
    boundary: str,
) -> None:
    adapter, path = guarded_adapter
    _write_version_json(path, "1")
    raw = path.read_text(encoding="utf-8")
    original_loads = json.loads
    message = "synthetic-decoder-secret-marker"
    injected = Mock(side_effect=decoder_error(message))

    def decode(value, *args, **kwargs):
        if value == raw:
            return injected()
        return original_loads(value, *args, **kwargs)

    with monkeypatch.context() as patch:
        # json is shared with HTTP response parsing; only the session text fails.
        patch.setattr("app.finary_session_store.json.loads", decode)
        _assert_decoding_rejection(
            adapter, path, caplog, boundary, "Finary session file is malformed", message
        )
        assert injected.call_count == 2
    # Restore the real decoder before checking explicit operator recovery.
    _assert_explicit_recovery(path)


def _assert_decoding_rejection(
    adapter: FinaryApiClient,
    path: Path,
    caplog: pytest.LogCaptureFixture,
    boundary: str,
    storage_message: str,
    decoder_message: str | None,
) -> None:
    assert len(path.read_bytes()) <= _MAX_FILE_BYTES
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.parent.stat().st_mode & 0o777 == 0o700
    lock = path.with_name(path.name + ".lock")
    before, lock_before = _file_identity(path), _file_identity(lock)
    assert len(lock_before[0]) == 32  # guarded_adapter established a public clear revision.
    directory_mode = path.parent.stat().st_mode
    store = FileFinarySessionStore(path, lock_timeout_seconds=0.05)

    async def request() -> Response:
        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
        ) as client:
            return await client.get(boundary, headers={"X-API-Key": "synthetic-bridge-key-marker"})

    for _ in range(2):
        if boundary in {"load", "snapshot"}:
            with pytest.raises(
                FinarySessionStoreError, match=f"^{storage_message}$"
            ):
                getattr(store, boundary)()
        elif boundary == "adapter":
            with pytest.raises(
                FinaryAuthenticationError, match="^Stored Finary session is unusable$"
            ):
                adapter.authenticate()
        else:
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
            assert "synthetic-" not in response.text
            if decoder_message is not None:
                assert decoder_message not in response.text
        assert _file_identity(path) == before
        assert _file_identity(lock) == lock_before
        assert path.parent.stat().st_mode == directory_mode
        if decoder_message is not None:
            assert decoder_message not in caplog.text
        for record in caplog.records:
            if decoder_message is not None:
                assert decoder_message not in repr(record.__dict__)
            assert record.exc_info is None
            assert record.exc_text is None
            assert record.stack_info is None


def _assert_explicit_recovery(path: Path) -> None:
    lock = path.with_name(path.name + ".lock")
    lock_before = _file_identity(lock)
    # Explicit operator replacement, only after proving rejection did not mutate state.
    # A fresh store opens a new lock descriptor and must not be blocked by a leaked lock.
    recovery = FileFinarySessionStore(path, lock_timeout_seconds=0.05)
    replacement = FinarySessionState("synthetic-replacement", "synthetic-rotation")
    recovery.save(replacement)
    assert recovery.load() == replacement
    assert lock.stat().st_ino == lock_before[2]
    assert lock.read_bytes() != lock_before[0]


@pytest.mark.parametrize("operation", ["load", "snapshot"])
def test_json_decoding_boundary_does_not_swallow_unrelated_runtime_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    store, path = _store(tmp_path)
    store.clear()
    _write_version_json(path, "1")
    failure = RuntimeError("synthetic programming failure")
    with monkeypatch.context() as patch:
        patch.setattr("app.finary_session_store.json.loads", Mock(side_effect=failure))
        with pytest.raises(RuntimeError) as caught:
            getattr(store, operation)()
        assert caught.value is failure
    assert store.load() == FinarySessionState(
        "synthetic-session-marker", "synthetic-cookie-marker"
    )


_INVALID_VERSION_JSON = [
    pytest.param("true", id="true"),
    pytest.param("false", id="false"),
    pytest.param("1.0", id="equal-float"),
    pytest.param("1e0", id="equal-exponent"),
    pytest.param("1.5", id="fraction"),
    pytest.param('"1"', id="numeric-string"),
    pytest.param('""', id="empty-string"),
    pytest.param("null", id="null"),
    pytest.param(None, id="missing"),
    pytest.param("[]", id="array"),
    pytest.param('{"synthetic-invalid-marker":"synthetic-value"}', id="object"),
    pytest.param("0", id="zero"),
    pytest.param("-1", id="negative"),
    pytest.param("2", id="future"),
]


def _write_version_json(path: Path, version_json: str | None) -> None:
    # Keep JSON tokens literal, especially exponent notation and boolean/float types.
    version_field = "" if version_json is None else f'"version":{version_json},'
    with path.open("x", encoding="utf-8") as stream:
        path.chmod(0o600)
        stream.write(
            "{" + version_field
            + '"session_id":"synthetic-session-marker",'
            '"client_cookie":"synthetic-cookie-marker"}'
        )


@pytest.mark.parametrize("version_json", _INVALID_VERSION_JSON)
@pytest.mark.parametrize("operation", ["load", "snapshot"])
def test_store_rejects_invalid_version_without_mutation(
    tmp_path: Path, version_json: str | None, operation: str
) -> None:
    store, path = _store(tmp_path)
    store.clear()
    _write_version_json(path, version_json)
    lock = path.with_name(path.name + ".lock")
    before, lock_before = _file_identity(path), _file_identity(lock)
    directory_mode = path.parent.stat().st_mode
    message = (
        "Finary session file has unexpected fields" if version_json is None
        else "Finary session file version is unsupported"
    )
    for _ in range(2):
        with pytest.raises(FinarySessionStoreError, match=f"^{message}$"):
            getattr(store, operation)()
        assert _file_identity(path) == before
        assert _file_identity(lock) == lock_before
        assert path.parent.stat().st_mode == directory_mode


@pytest.mark.parametrize("existing_revision", [False, True])
def test_integer_version_loads_without_rewriting(
    tmp_path: Path, existing_revision: bool
) -> None:
    store, path = _store(tmp_path)
    if existing_revision:
        store.clear()
    _write_version_json(path, "1")
    before = _file_identity(path)
    snapshot = store.snapshot()
    lock = path.with_name(path.name + ".lock")
    lock_before = _file_identity(lock)
    assert bool(snapshot.revision) is existing_revision
    for _ in range(2):
        assert store.snapshot() == snapshot
        assert store.load() == FinarySessionState(
            "synthetic-session-marker", "synthetic-cookie-marker"
        )
        assert _file_identity(path) == before
        assert _file_identity(lock) == lock_before


@pytest.mark.parametrize("version_json", _INVALID_VERSION_JSON)
@pytest.mark.parametrize("boundary", ["adapter", "/v1/snapshot", "/v2/snapshot"])
def test_invalid_version_stops_before_authentication_and_preserves_file(
    guarded_adapter: tuple[FinaryApiClient, Path], version_json: str | None, boundary: str
) -> None:
    adapter, path = guarded_adapter
    _write_version_json(path, version_json)
    lock = path.with_name(path.name + ".lock")
    before, lock_before = _file_identity(path), _file_identity(lock)
    directory_mode = path.parent.stat().st_mode

    async def request() -> Response:
        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
        ) as client:
            return await client.get(boundary, headers={"X-API-Key": "synthetic-bridge-key-marker"})

    for _ in range(2):
        if boundary == "adapter":
            with pytest.raises(
                FinaryAuthenticationError, match="^Stored Finary session is unusable$"
            ):
                adapter.authenticate()
        else:
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
            assert "synthetic-" not in response.text
        assert _file_identity(path) == before
        assert _file_identity(lock) == lock_before
        assert path.parent.stat().st_mode == directory_mode
