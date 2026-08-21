"""Tests for the protected local Finary session-state store."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from app.finary_session_store import (
    FileFinarySessionStore,
    FinarySessionState,
    FinarySessionStoreError,
)


def _store(tmp_path: Path) -> tuple[FileFinarySessionStore, Path]:
    private_directory = tmp_path / "private-session"
    private_directory.mkdir(mode=0o700)
    path = private_directory / "session.json"
    return FileFinarySessionStore(path), path


def _state(*, suffix: str = "001") -> FinarySessionState:
    return FinarySessionState(
        session_id=f"session-synthetic-{suffix}",
        client_cookie=f"client-cookie-synthetic-{suffix}",
    )


def test_store_saves_loads_and_clears_minimum_state(tmp_path: Path) -> None:
    store, path = _store(tmp_path)

    assert store.load() is None
    store.save(_state())

    assert store.load() == _state()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700

    store.clear()
    assert store.load() is None


@pytest.mark.parametrize(
    "payload",
    [
        "not-json",
        json.dumps({"version": 99, "session_id": "x", "client_cookie": "y"}),
        json.dumps(
            {
                "version": 1,
                "session_id": "x",
                "client_cookie": "y",
                "raw_response": {},
            }
        ),
        json.dumps({"version": 1, "session_id": "", "client_cookie": "y"}),
    ],
)
def test_store_rejects_malformed_or_unsupported_state(tmp_path: Path, payload: str) -> None:
    store, path = _store(tmp_path)
    path.write_text(payload, encoding="utf-8")
    path.chmod(0o600)

    with pytest.raises(FinarySessionStoreError):
        store.load()


def test_store_rejects_broad_file_permissions(tmp_path: Path) -> None:
    store, path = _store(tmp_path)
    store.save(_state())
    path.chmod(0o644)

    with pytest.raises(FinarySessionStoreError, match="permissions"):
        store.load()


def test_store_rejects_broad_directory_permissions(tmp_path: Path) -> None:
    store, path = _store(tmp_path)
    store.save(_state())
    path.parent.chmod(0o755)

    with pytest.raises(FinarySessionStoreError, match="directory permissions"):
        store.load()


def test_store_requires_absolute_path() -> None:
    with pytest.raises(ValueError, match="absolute"):
        FileFinarySessionStore("relative/session.json")


def test_store_loads_missing_parent_as_empty(tmp_path: Path) -> None:
    store = FileFinarySessionStore(tmp_path / "missing" / "session.json")

    assert store.load() is None


def test_atomic_save_failure_preserves_previous_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, _ = _store(tmp_path)
    store.save(_state(suffix="old"))

    def fail_replace(source: object, destination: object) -> None:
        del source, destination
        raise OSError("synthetic atomic replace failure")

    monkeypatch.setattr(os, "replace", fail_replace)

    with pytest.raises(FinarySessionStoreError, match="could not be saved"):
        store.save(_state(suffix="new"))

    assert store.load() == _state(suffix="old")


def test_serialized_state_excludes_stronger_credentials(tmp_path: Path) -> None:
    store, path = _store(tmp_path)
    store.save(_state())
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert set(payload) == {"version", "session_id", "client_cookie"}
    for prohibited in (
        "password",
        "mfa_code",
        "totp",
        "totp_secret",
        "backup_code",
        "recovery_code",
        "bearer_token",
        "raw_response",
    ):
        assert prohibited not in payload
