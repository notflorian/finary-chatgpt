"""Install authorized staging OAuth state into one fresh local Compose project."""

from __future__ import annotations

import argparse
import asyncio
import hmac
import json
import os
import re
import stat
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from app.mcp_auth import ISSUER, OAuthState, OAuthStore, private_stat
from app.mcp_client import McpFailure

ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILE = ROOT / "docker-compose.yml"
DESTINATION_DIRECTORY = "/var/lib/finary-mcp/state"
DESTINATION_STATE = DESTINATION_DIRECTORY + "/oauth.json"
VOLUME_TARGET = "/var/lib/finary-mcp"
MAX_STATE_BYTES = 32768
PROJECT_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")
IMAGE_ID = re.compile(r"^(?:sha256:)?[0-9a-f]{64}$")
KNOWN_SOURCE_NAMES = {"oauth.json", "oauth.json.lock", "oauth.json.lease"}

TRANSFER_WORKER = r'''
# OAUTH_HANDOFF_TRANSFER_WORKER
import json
import os
import stat
import sys

directory = "/var/lib/finary-mcp/state"
state = directory + "/oauth.json"
try:
    os.lstat(directory)
except FileNotFoundError:
    pass
except OSError:
    raise SystemExit(23)
else:
    raise SystemExit(20)
try:
    os.mkdir(directory, 0o700)
    fd = os.open(state, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
except FileExistsError:
    raise SystemExit(20)
except OSError:
    raise SystemExit(23)
try:
    data = sys.stdin.buffer.read(32769)
    if not data or len(data) > 32768:
        raise ValueError
    offset = 0
    while offset < len(data):
        offset += os.write(fd, data[offset:])
    os.fchmod(fd, 0o600)
    os.fsync(fd)
except Exception:
    raise SystemExit(21) from None
finally:
    os.close(fd)
try:
    directory_fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
except OSError:
    raise SystemExit(21) from None
print(json.dumps({"status": "TRANSFERRED"}))
'''

VERIFY_WORKER = r'''
# OAUTH_HANDOFF_VERIFY_WORKER
import hmac
import json
import os
import stat
import sys

directory = "/var/lib/finary-mcp/state"
state = directory + "/oauth.json"
try:
    directory_info = os.lstat(directory)
    file_info = os.lstat(state)
    expected = sys.stdin.buffer.read(32769)
    with open(state, "rb") as stream:
        actual = stream.read(32769)
    private_modes = (
        stat.S_IMODE(directory_info.st_mode) == 0o700
        and stat.S_IMODE(file_info.st_mode) == 0o600
        and stat.S_ISDIR(directory_info.st_mode)
        and stat.S_ISREG(file_info.st_mode)
    )
    runtime_owner = (
        directory_info.st_uid == os.getuid() == 0
        and file_info.st_uid == os.getuid()
        and directory_info.st_gid == os.getgid() == 0
        and file_info.st_gid == os.getgid()
    )
    content_match = (
        0 < len(expected) <= 32768
        and len(actual) <= 32768
        and hmac.compare_digest(expected, actual)
    )
    if not private_modes or not runtime_owner or not content_match:
        raise ValueError
except Exception:
    raise SystemExit(22) from None
print(json.dumps({
    "status": "DESTINATION_CONTENT_VERIFIED",
    "content_match": True,
    "private_modes": True,
    "runtime_owner": True,
}))
'''

Runner = Callable[..., subprocess.CompletedProcess[bytes]]


class HandoffFailure(Exception):
    """A fixed failure code safe to show without underlying process output."""

    def __init__(
        self,
        code: str,
        *,
        verified: bool = False,
        destination_touched: bool = False,
        bridge_state: str | None = None,
    ):
        super().__init__(code)
        self.code = code
        self.verified = verified
        self.destination_touched = destination_touched
        self.bridge_state = bridge_state


def _fail(
    code: str,
    *,
    verified: bool = False,
    destination_touched: bool = False,
    bridge_state: str | None = None,
) -> None:
    raise HandoffFailure(
        code,
        verified=verified,
        destination_touched=destination_touched,
        bridge_state=bridge_state,
    )


def _private_regular(path: Path) -> os.stat_result:
    info = path.lstat()
    private_stat(info, 0o600)
    if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_STATE_BYTES:
        raise McpFailure("MCP_AUTH_UNAVAILABLE")
    return info


def _preflight_source(path: Path) -> OAuthStore:
    try:
        if not path.is_absolute():
            raise McpFailure("MCP_AUTH_UNAVAILABLE")
        directory_info = path.parent.lstat()
        if not stat.S_ISDIR(directory_info.st_mode):
            raise McpFailure("MCP_AUTH_UNAVAILABLE")
        private_stat(directory_info, 0o700)
        _private_regular(path)
        for suffix in (".lock", ".lease"):
            coordination = Path(str(path) + suffix)
            if coordination.exists() or coordination.is_symlink():
                _private_regular(coordination)
        store = OAuthStore(path)
        _require_renewable(store._read())
        return store
    except (McpFailure, OSError, TypeError, ValueError):
        _fail("SOURCE_INVALID")


def _require_renewable(state: OAuthState) -> None:
    if (
        not state.generation
        or not state.refresh_token
        or not state.client
        or state.client.get("issuer") != ISSUER
    ):
        raise McpFailure("MCP_AUTH_UNAVAILABLE")


def _read_source_bytes(path: Path) -> bytes:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            private_stat(info, 0o600)
            if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= MAX_STATE_BYTES:
                raise McpFailure("MCP_AUTH_UNAVAILABLE")
            data = stream.read(MAX_STATE_BYTES + 1)
        if not data or len(data) > MAX_STATE_BYTES:
            raise McpFailure("MCP_AUTH_UNAVAILABLE")
        return data
    except (McpFailure, OSError):
        _fail("SOURCE_INVALID")


def _preflight_cleanup(path: Path) -> None:
    try:
        if not path.parent.name.startswith("finary-mcp-bootstrap."):
            raise ValueError
        names = {entry.name for entry in path.parent.iterdir()}
        if not names <= KNOWN_SOURCE_NAMES or path.name != "oauth.json":
            raise ValueError
    except (OSError, ValueError):
        _fail("SOURCE_CLEANUP_UNSAFE")


def _run(
    runner: Runner,
    args: list[str],
    *,
    timeout: int,
    input_bytes: bytes | None = None,
) -> subprocess.CompletedProcess[bytes]:
    try:
        return runner(
            args,
            cwd=ROOT,
            input=input_bytes,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except (FileNotFoundError, PermissionError, subprocess.TimeoutExpired, OSError):
        _fail("DOCKER_UNAVAILABLE", bridge_state="UNVERIFIED")


class DockerDestination:
    def __init__(self, project_name: str, runner: Runner) -> None:
        self.runner = runner
        self.project_name = project_name
        self.compose = [
            "docker",
            "compose",
            "--project-directory",
            str(ROOT),
            "-f",
            str(COMPOSE_FILE),
            "-p",
            project_name,
        ]
        self.volume = ""
        self.image = ""
        self.bridge_state = "UNVERIFIED"

    def _compose(self, *arguments: str, timeout: int = 30) -> subprocess.CompletedProcess[bytes]:
        return _run(self.runner, [*self.compose, *arguments], timeout=timeout)

    def configure(self) -> None:
        result = self._compose("config", "--format", "json")
        if result.returncode != 0:
            _fail("DOCKER_UNAVAILABLE")
        try:
            config = json.loads(result.stdout)
            service = config["services"]["finary-bridge"]
            mounts = [
                mount
                for mount in service["volumes"]
                if mount.get("target") == VOLUME_TARGET
            ]
            if (
                service["environment"]["FINARY_MCP_STATE_PATH"] != DESTINATION_STATE
                or service.get("user") not in (None, "", "0", "root", "0:0")
                or len(mounts) != 1
                or mounts[0].get("type") != "volume"
            ):
                raise ValueError
            source = mounts[0]["source"]
            volume = config["volumes"][source]["name"]
            shared_services = [
                name
                for name, candidate in config["services"].items()
                if name != "finary-bridge"
                and any(
                    mount.get("type") == "volume" and mount.get("source") == source
                    for mount in candidate.get("volumes", [])
                )
            ]
            if not isinstance(volume, str) or not volume:
                raise ValueError
            if shared_services:
                raise ValueError
            self.volume = volume
        except (
            AttributeError,
            KeyError,
            TypeError,
            ValueError,
            json.JSONDecodeError,
            UnicodeDecodeError,
        ):
            _fail("COMPOSE_CONFIGURATION_INVALID")

    def require_stopped(self) -> None:
        self.bridge_state = "UNVERIFIED"
        result = self._compose("ps", "--all", "--format", "json", "finary-bridge")
        if result.returncode != 0:
            _fail("DOCKER_UNAVAILABLE", bridge_state="UNVERIFIED")
        try:
            records = []
            for line in result.stdout.splitlines():
                value = json.loads(line)
                records.extend(value if isinstance(value, list) else [value])
            states = []
            for record in records:
                if not isinstance(record, dict) or record.get("Service") != "finary-bridge":
                    raise ValueError
                state = record["State"]
                if not isinstance(state, str) or not state.strip():
                    raise ValueError
                states.append(state.strip().lower())
        except (
            AttributeError,
            KeyError,
            TypeError,
            ValueError,
            json.JSONDecodeError,
            UnicodeDecodeError,
        ):
            _fail("DESTINATION_STATUS_UNVERIFIED", bridge_state="UNVERIFIED")
        if "running" in states:
            self.bridge_state = "RUNNING"
            _fail("DESTINATION_BRIDGE_RUNNING", bridge_state="RUNNING")
        if any(state not in {"created", "exited"} for state in states):
            self.bridge_state = "NOT_STOPPED"
            _fail("DESTINATION_BRIDGE_NOT_STOPPED", bridge_state="NOT_STOPPED")
        self.bridge_state = "STOPPED"

    def build(self) -> None:
        result = self._compose("build", "finary-bridge", timeout=300)
        if result.returncode != 0:
            _fail("DESTINATION_IMAGE_FAILED")
        repository = self.project_name + "-finary-bridge"
        inspected = _run(
            self.runner,
            ["docker", "image", "inspect", repository],
            timeout=30,
        )
        try:
            images = json.loads(inspected.stdout)
            if not isinstance(images, list) or len(images) != 1:
                raise ValueError
            image_id = images[0]["Id"]
            configured_user = images[0]["Config"].get("User", "")
        except (
            AttributeError,
            KeyError,
            TypeError,
            ValueError,
            json.JSONDecodeError,
            UnicodeDecodeError,
        ):
            image_id = configured_user = None
        if (
            inspected.returncode != 0
            or not isinstance(image_id, str)
            or not IMAGE_ID.fullmatch(image_id)
            or configured_user not in ("", "0", "root")
        ):
            _fail("DESTINATION_RUNTIME_UNSUPPORTED")
        self.image = image_id

    def ensure_volume(self) -> None:
        inspected = _run(
            self.runner,
            ["docker", "volume", "inspect", self.volume],
            timeout=30,
        )
        if inspected.returncode == 0:
            try:
                volumes = json.loads(inspected.stdout)
                if not isinstance(volumes, list) or len(volumes) != 1:
                    raise ValueError
                volume = volumes[0]
                labels = volume["Labels"]
                valid = (
                    volume["Name"] == self.volume
                    and labels["com.docker.compose.project"] == self.project_name
                    and labels["com.docker.compose.volume"] == "finary_mcp_data"
                )
            except (
                KeyError,
                TypeError,
                ValueError,
                json.JSONDecodeError,
                UnicodeDecodeError,
            ):
                valid = False
            if not valid:
                _fail("DESTINATION_CREATION_FAILED")
            return
        created = _run(
            self.runner,
            [
                "docker",
                "volume",
                "create",
                "--label",
                "com.docker.compose.project=" + self.project_name,
                "--label",
                "com.docker.compose.volume=finary_mcp_data",
                self.volume,
            ],
            timeout=30,
        )
        created_name = created.stdout.decode("utf-8", "ignore").strip()
        if created.returncode != 0 or created_name != self.volume:
            _fail("DESTINATION_CREATION_FAILED")

    def _container(
        self,
        arguments: list[str],
        *,
        input_bytes: bytes | None = None,
    ) -> subprocess.CompletedProcess[bytes]:
        return _run(
            self.runner,
            [
                "docker",
                "run",
                "--rm",
                *(["-i"] if input_bytes is not None else []),
                "--network",
                "none",
                "--mount",
                f"type=volume,source={self.volume},target={VOLUME_TARGET}",
                self.image,
                *arguments,
            ],
            timeout=60,
            input_bytes=input_bytes,
        )

    def transfer(self, source: bytes) -> None:
        result = self._container(["python", "-c", TRANSFER_WORKER], input_bytes=source)
        if result.returncode == 20:
            _fail("DESTINATION_EXISTS", destination_touched=True)
        if result.returncode == 23:
            _fail("DESTINATION_CREATION_FAILED", destination_touched=True)
        if result.returncode != 0:
            _fail("DESTINATION_TRANSFER_FAILED", destination_touched=True)
        try:
            payload = json.loads(result.stdout)
        except (json.JSONDecodeError, UnicodeDecodeError):
            payload = None
        if payload != {"status": "TRANSFERRED"}:
            _fail("DESTINATION_TRANSFER_FAILED", destination_touched=True)

    def validate(self, source: bytes, generation: str) -> None:
        status = self._container(
            ["python", "-m", "app.mcp_auth", "status", "--state", DESTINATION_STATE]
        )
        try:
            payload = json.loads(status.stdout)
        except (json.JSONDecodeError, UnicodeDecodeError):
            payload = None
        if (
            status.returncode != 0
            or not isinstance(payload, dict)
            or payload.get("status") != "RENEWABLE_STATE_PRESENT"
            or payload.get("live_validity") != "UNVERIFIED"
            or not payload.get("generation")
        ):
            _fail("DESTINATION_VALIDATION_FAILED", destination_touched=True)
        if payload["generation"] != generation:
            _fail("DESTINATION_GENERATION_MISMATCH", destination_touched=True)
        verified = self._container(["python", "-c", VERIFY_WORKER], input_bytes=source)
        try:
            verification = json.loads(verified.stdout)
        except (json.JSONDecodeError, UnicodeDecodeError):
            verification = None
        expected = {
            "status": "DESTINATION_CONTENT_VERIFIED",
            "content_match": True,
            "private_modes": True,
            "runtime_owner": True,
        }
        if verified.returncode != 0 or verification != expected:
            _fail("DESTINATION_VALIDATION_FAILED", destination_touched=True)


def _same_open_file(path: Path, fd: int) -> bool:
    path_info = path.lstat()
    file_info = os.fstat(fd)
    return (path_info.st_dev, path_info.st_ino) == (file_info.st_dev, file_info.st_ino)


def _cleanup_source(
    store: OAuthStore,
    expected_source: bytes,
    expected_generation: str,
    lease_fd: int,
) -> None:
    path = store.path
    lock_path = Path(str(path) + ".lock")
    lease_path = Path(str(path) + ".lease")
    try:
        _preflight_cleanup(path)
        with store.locked() as lock_fd:
            _preflight_cleanup(path)
            for coordination, fd in ((lock_path, lock_fd), (lease_path, lease_fd)):
                private_stat(os.fstat(fd), 0o600)
                if not stat.S_ISREG(os.fstat(fd).st_mode) or not _same_open_file(
                    coordination, fd
                ):
                    raise McpFailure("MCP_AUTH_UNAVAILABLE")
            current = store._read()
            _require_renewable(current)
            if current.generation != expected_generation:
                raise McpFailure("MCP_AUTH_UNAVAILABLE")
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            try:
                info = os.fstat(fd)
                private_stat(info, 0o600)
                if not stat.S_ISREG(info.st_mode) or not _same_open_file(path, fd):
                    raise McpFailure("MCP_AUTH_UNAVAILABLE")
                actual = os.read(fd, MAX_STATE_BYTES + 1)
            finally:
                os.close(fd)
            if not hmac.compare_digest(actual, expected_source):
                raise McpFailure("MCP_AUTH_UNAVAILABLE")
            path.unlink()
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
            lock_path.unlink()
            lease_path.unlink()
            path.parent.rmdir()
    except (HandoffFailure, McpFailure, OSError, TypeError, ValueError):
        _fail("SOURCE_CLEANUP_FAILED", verified=True, destination_touched=True)


async def _transfer_with_lease(
    store: OAuthStore,
    destination: DockerDestination,
    cleanup_source: bool,
) -> None:
    try:
        async with store.lease() as lease_fd:
            try:
                state = store.read()
                _require_renewable(state)
            except McpFailure:
                _fail("SOURCE_INVALID")
            source = _read_source_bytes(store.path)
            destination.build()
            destination.require_stopped()
            destination.ensure_volume()
            destination.transfer(source)
            destination.validate(source, state.generation)
            destination.require_stopped()
            if cleanup_source:
                _cleanup_source(store, source, state.generation, lease_fd)
    except HandoffFailure:
        raise
    except McpFailure:
        _fail("SOURCE_ACTIVE")
    except OSError:
        _fail("SOURCE_UNAVAILABLE")


def handoff(
    source: Path,
    project_name: str,
    cleanup_source: bool,
    *,
    runner: Runner | None = None,
) -> dict[str, str | bool]:
    if runner is None:
        runner = subprocess.run
    if not PROJECT_NAME.fullmatch(project_name):
        _fail("PROJECT_NAME_INVALID")
    store = _preflight_source(source)
    if cleanup_source:
        _preflight_cleanup(source)
    destination = DockerDestination(project_name, runner)
    try:
        destination.configure()
        destination.require_stopped()
        asyncio.run(_transfer_with_lease(store, destination, cleanup_source))
    except HandoffFailure as error:
        if error.bridge_state is None:
            error.bridge_state = destination.bridge_state
        raise
    return {
        "status": "OAUTH_STATE_HANDOFF_VERIFIED",
        "bridge": "STOPPED",
        "renewable_state": True,
        "generation_match": True,
        "source_cleanup": "REMOVED" if cleanup_source else "RETAINED",
    }


def _failure_payload(error: HandoffFailure) -> dict[str, str | bool]:
    bridge_state = error.bridge_state or "UNVERIFIED"
    if error.verified:
        return {
            "status": "OAUTH_STATE_HANDOFF_VERIFIED_CLEANUP_FAILED",
            "reason": error.code,
            "bridge": bridge_state,
            "destination_verified": True,
            "source_cleanup": "FAILED",
            "action": "Inspect only the designated staging directory; do not repeat the handoff.",
        }
    action = "Correct the prerequisite and retry with the original staging state."
    if error.destination_touched:
        action = (
            "Keep the bridge stopped and inspect the destination and original staging state; "
            "do not overwrite or automatically retry."
        )
    return {
        "status": "OAUTH_STATE_HANDOFF_FAILED",
        "reason": error.code,
        "bridge": bridge_state,
        "source_cleanup": "NOT_ATTEMPTED",
        "action": action,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Fresh-install-only transfer of authorized MCP OAuth state into a stopped local "
            "Compose project; this is not an upgrade or credential migration command."
        )
    )
    parser.add_argument("--source", type=Path, required=True, help="Absolute staging oauth.json")
    parser.add_argument(
        "--project-name",
        required=True,
        help="Explicit local Docker Compose project name",
    )
    parser.add_argument(
        "--cleanup-source",
        action="store_true",
        help="After verification, remove only the designated temporary staging directory",
    )
    args = parser.parse_args()
    try:
        outcome = handoff(args.source, args.project_name, args.cleanup_source)
    except HandoffFailure as error:
        print(json.dumps(_failure_payload(error), sort_keys=True), file=sys.stderr)
        raise SystemExit(3 if error.verified else 2) from None
    print(json.dumps(outcome, sort_keys=True))


if __name__ == "__main__":
    main()
