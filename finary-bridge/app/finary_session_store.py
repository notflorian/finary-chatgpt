"""Protected local persistence for the minimum refreshable Clerk session state."""

from __future__ import annotations

import fcntl
import json
import os
import stat
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from pathlib import Path
from time import monotonic, sleep
from typing import Final, Protocol
from uuid import uuid4

_FORMAT_VERSION: Final = 1
_MAX_FILE_BYTES: Final = 32_768
_MAX_SESSION_ID_LENGTH: Final = 512
_MAX_CLIENT_COOKIE_LENGTH: Final = 16_384


class FinarySessionStoreError(Exception):
    """Stored authentication state is missing required security or structure."""


@dataclass(frozen=True, slots=True)
class FinarySessionState:
    """Minimum bearer-equivalent state required by Clerk session refresh."""

    session_id: str = field(repr=False)
    client_cookie: str = field(repr=False)

    def __post_init__(self) -> None:
        if not self.session_id or len(self.session_id) > _MAX_SESSION_ID_LENGTH:
            raise ValueError("session_id is empty or too long")
        if not self.client_cookie or len(self.client_cookie) > _MAX_CLIENT_COOKIE_LENGTH:
            raise ValueError("client_cookie is empty or too long")


@dataclass(frozen=True, slots=True)
class FinarySessionSnapshot:
    """Ownership ticket, including absence and non-secret storage revision."""

    state: FinarySessionState | None = field(repr=False)
    revision: str = field(repr=False)


class FinarySessionStore(Protocol):
    """Adapter-owned storage boundary for refreshable authentication state."""

    def snapshot(self) -> FinarySessionSnapshot:
        """Read state and ownership atomically."""

    def compare_and_swap(
        self, expected: FinarySessionSnapshot, state: FinarySessionState | None
    ) -> FinarySessionSnapshot | None:
        """Mutate only the observed revision; None means ownership was lost."""

    def load(self) -> FinarySessionState | None:
        """Load strictly validated state, or return None when it is absent."""

    def save(self, state: FinarySessionState) -> None:
        """Persist state atomically with restrictive permissions."""

    def clear(self) -> None:
        """Remove persisted state if present."""


class FileFinarySessionStore:
    """Versioned JSON store in an operator-controlled private directory."""

    def __init__(self, path: str | Path, *, lock_timeout_seconds: float = 2.0) -> None:
        if not 0 < lock_timeout_seconds <= 30:
            raise ValueError("Session lock timeout must be between zero and 30 seconds")
        self._lock_timeout_seconds = lock_timeout_seconds
        self._path = Path(path)
        if not self._path.is_absolute():
            raise ValueError("Finary session path must be absolute")

    @contextmanager
    def _locked(self) -> Iterator[int]:
        # Stable sibling inode: never lock the session file replaced by save().
        # No network or interactive work is allowed inside this critical section.
        self._ensure_private_directory(self._path.parent)
        descriptor = None
        try:
            descriptor = os.open(
                self._path.with_name(self._path.name + ".lock"),
                os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
                0o600,
            )
            self._validate_file_security(os.fstat(descriptor))
            deadline = monotonic() + self._lock_timeout_seconds
            while True:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if monotonic() >= deadline:
                        raise FinarySessionStoreError("Finary session store is busy") from None
                    sleep(min(0.01, max(0, deadline - monotonic())))
            yield descriptor
        except OSError:
            raise FinarySessionStoreError("Finary session storage operation failed") from None
        finally:
            if descriptor is not None:
                os.close(descriptor)  # Also releases flock on every failure path.

    def _snapshot_locked(self, descriptor: int) -> FinarySessionSnapshot:
        revision = os.pread(descriptor, 65, 0)
        if revision and (
            len(revision) != 32 or any(c not in b"0123456789abcdef" for c in revision)
        ):
            raise FinarySessionStoreError("Finary session revision is invalid")
        return FinarySessionSnapshot(self._load(), revision.decode("ascii"))

    def snapshot(self) -> FinarySessionSnapshot:
        with self._locked() as descriptor:
            return self._snapshot_locked(descriptor)

    def load(self) -> FinarySessionState | None:
        return self.snapshot().state

    def save(self, state: FinarySessionState) -> None:
        """Explicit replacement: always creates a new revision, even for equal state."""
        with self._locked() as descriptor:
            self._mutate_locked(descriptor, state)

    def clear(self) -> None:
        """Explicit clearing also supersedes pending sign-ins that observed absence."""
        with self._locked() as descriptor:
            self._mutate_locked(descriptor, None)

    def compare_and_swap(
        self, expected: FinarySessionSnapshot, state: FinarySessionState | None
    ) -> FinarySessionSnapshot | None:
        with self._locked() as descriptor:
            if self._snapshot_locked(descriptor) != expected:
                return None
            return self._mutate_locked(descriptor, state)

    def _mutate_locked(
        self, descriptor: int, state: FinarySessionState | None
    ) -> FinarySessionSnapshot:
        if self._path.is_symlink():
            raise FinarySessionStoreError("Finary session file cannot be a symlink")
        with suppress(FileNotFoundError):
            self._validate_file_security(self._path.stat())
        revision = uuid4().hex
        # Invalidate previous ownership before mutation, including partial I/O
        # failures. The lock file contains metadata only, never authentication.
        if os.pwrite(descriptor, revision.encode("ascii"), 0) != 32:
            raise FinarySessionStoreError("Finary session revision could not be saved")
        os.ftruncate(descriptor, 32)
        os.fsync(descriptor)
        if state is None:
            self._clear()
        else:
            self._save(state)
        return FinarySessionSnapshot(state, revision)

    def _load(self) -> FinarySessionState | None:
        if not self._path.parent.exists():
            return None
        self._validate_private_directory(self._path.parent)
        if self._path.is_symlink():
            raise FinarySessionStoreError("Finary session file cannot be a symlink")
        try:
            file_stat = self._path.stat()
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise FinarySessionStoreError("Finary session file is unreadable") from exc

        self._validate_file_security(file_stat)
        if file_stat.st_size > _MAX_FILE_BYTES:
            raise FinarySessionStoreError("Finary session file is too large")

        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise FinarySessionStoreError("Finary session file is malformed") from exc

        if not isinstance(payload, dict) or set(payload) != {
            "version",
            "session_id",
            "client_cookie",
        }:
            raise FinarySessionStoreError("Finary session file has unexpected fields")
        if payload["version"] != _FORMAT_VERSION:
            raise FinarySessionStoreError("Finary session file version is unsupported")
        try:
            return FinarySessionState(
                session_id=payload["session_id"],
                client_cookie=payload["client_cookie"],
            )
        except (TypeError, ValueError) as exc:
            raise FinarySessionStoreError("Finary session file is malformed") from exc

    def _save(self, state: FinarySessionState) -> None:
        parent = self._path.parent
        self._ensure_private_directory(parent)
        if self._path.is_symlink():
            raise FinarySessionStoreError("Finary session file cannot be a symlink")

        payload = json.dumps(
            {
                "version": _FORMAT_VERSION,
                "session_id": state.session_id,
                "client_cookie": state.client_cookie,
            },
            separators=(",", ":"),
            sort_keys=True,
        )
        temporary_path: Path | None = None
        try:
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=".finary-session-",
                dir=parent,
            )
            temporary_path = Path(temporary_name)
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_path, self._path)
            temporary_path = None
            os.chmod(self._path, 0o600)
            directory_descriptor = os.open(parent, os.O_RDONLY)
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
        except OSError as exc:
            raise FinarySessionStoreError("Finary session file could not be saved") from exc
        finally:
            if temporary_path is not None:
                with suppress(OSError):
                    temporary_path.unlink(missing_ok=True)

    def _clear(self) -> None:
        try:
            self._path.unlink(missing_ok=True)
        except OSError as exc:
            raise FinarySessionStoreError("Finary session file could not be cleared") from exc

    def _ensure_private_directory(self, directory: Path) -> None:
        try:
            directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        except OSError as exc:
            raise FinarySessionStoreError("Finary session directory is unavailable") from exc
        self._validate_private_directory(directory)

    def _validate_private_directory(self, directory: Path) -> None:
        try:
            directory_stat = directory.stat()
        except OSError as exc:
            raise FinarySessionStoreError("Finary session directory is unavailable") from exc
        if directory.is_symlink() or not stat.S_ISDIR(directory_stat.st_mode):
            raise FinarySessionStoreError("Finary session directory is invalid")
        if stat.S_IMODE(directory_stat.st_mode) & 0o077:
            raise FinarySessionStoreError("Finary session directory permissions are too broad")
        if hasattr(os, "geteuid") and directory_stat.st_uid != os.geteuid():
            raise FinarySessionStoreError("Finary session directory owner is invalid")

    def _validate_file_security(self, file_stat: os.stat_result) -> None:
        if not stat.S_ISREG(file_stat.st_mode):
            raise FinarySessionStoreError("Finary session path is not a regular file")
        if stat.S_IMODE(file_stat.st_mode) & 0o077:
            raise FinarySessionStoreError("Finary session file permissions are too broad")
        if hasattr(os, "geteuid") and file_stat.st_uid != os.geteuid():
            raise FinarySessionStoreError("Finary session file owner is invalid")
