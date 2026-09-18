"""Fresh-install transfer of synthetic OAuth state into a Compose volume."""

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from uuid import UUID, uuid4

import pytest

import app.mcp_auth as auth

ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "scripts/handoff-mcp-oauth-state.py"
DESTINATION = "/var/lib/finary-mcp/state/oauth.json"
SECRET = b"synthetic-secret-marker"


@pytest.fixture
def handoff_module():
    assert SCRIPT.is_file()
    spec = importlib.util.spec_from_file_location("handoff_mcp_oauth_state", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def source_state(tmp_path, *, directory="finary-mcp-bootstrap.synthetic", **changes):
    parent = tmp_path / directory
    parent.mkdir(mode=0o700, parents=True)
    generation = str(uuid4())
    value = {
        "format": 1,
        "generation": generation,
        "client": {
            "client_id": "synthetic-local-client",
            "issuer": auth.ISSUER,
            "redirect_uris": [auth.CALLBACK],
            "token_endpoint_auth_method": "none",
        },
        "refresh_token": "synthetic-renewable-token",
        "scope": "openid offline_access",
    }
    value.update(changes)
    path = parent / "oauth.json"
    path.write_text(json.dumps(value, separators=(",", ":")))
    path.chmod(0o600)
    return path, generation


class FakeRunner:
    def __init__(self, *, failure=None):
        self.failure = failure
        self.calls = []
        self.destination = None
        self.project = None
        self.volume_exists = failure in {"existing_destination", "wrong_volume_labels"}
        if failure == "existing_destination":
            self.destination = b"existing destination"

    @staticmethod
    def result(args, returncode=0, stdout=b"", stderr=b""):
        return subprocess.CompletedProcess(args, returncode, stdout, stderr)

    def __call__(self, args, **kwargs):
        args = list(args)
        self.calls.append((args, kwargs))
        if self.failure == "docker_unavailable":
            raise FileNotFoundError("docker is unavailable: synthetic-secret-marker")
        if "config" in args and "--format" in args:
            project = args[args.index("-p") + 1]
            self.project = project
            config = {
                "services": {
                    "finary-bridge": {
                        "environment": {"FINARY_MCP_STATE_PATH": DESTINATION},
                        "user": "1000:1000" if self.failure == "non_root_service" else None,
                        "volumes": [
                            {
                                "type": "volume",
                                "source": "finary_mcp_data",
                                "target": "/var/lib/finary-mcp",
                            }
                        ],
                    }
                },
                "volumes": {
                    "finary_mcp_data": {"name": f"{project}_finary_mcp_data"}
                },
            }
            if self.failure == "shared_volume":
                config["services"]["n8n"] = {
                    "volumes": [
                        {
                            "type": "volume",
                            "source": "finary_mcp_data",
                            "target": "/untrusted",
                        }
                    ]
                }
            return self.result(args, stdout=json.dumps(config).encode())
        if "ps" in args:
            state = {
                "running": "running",
                "paused": "paused",
                "restarting": "restarting",
                "removing": "removing",
                "dead": "dead",
            }.get(self.failure)
            if self.failure == "invalid_status":
                stdout = b'{"Service":"finary-bridge"}\n'
            elif state:
                stdout = json.dumps(
                    {"Service": "finary-bridge", "State": state}
                ).encode() + b"\n"
            else:
                stdout = b""
            return self.result(args, stdout=stdout)
        if "build" in args:
            return self.result(args)
        if "images" in args:
            return self.result(args)
        if args[1:3] == ["image", "inspect"]:
            assert args[3] == f"{self.project}-finary-bridge"
            assert args[4:] == []
            config = {"User": "1000"} if self.failure == "non_root_image" else {}
            payload = [{"Id": "sha256:" + "1" * 64, "Config": config}]
            return self.result(args, stdout=json.dumps(payload).encode())
        if args[1:3] == ["volume", "inspect"]:
            if self.volume_exists:
                project = "wrong-project" if self.failure == "wrong_volume_labels" else self.project
                payload = [
                    {
                        "Name": args[3],
                        "Labels": {
                            "com.docker.compose.project": project,
                            "com.docker.compose.volume": "finary_mcp_data",
                        },
                    }
                ]
                return self.result(args, stdout=json.dumps(payload).encode())
            return self.result(args, returncode=1, stderr=SECRET)
        if args[1:3] == ["volume", "create"]:
            if self.failure == "destination_creation":
                return self.result(args, returncode=1, stderr=SECRET)
            self.volume_exists = True
            return self.result(args, stdout=(args[-1] + "\n").encode())
        if args[1] == "run" and "OAUTH_HANDOFF_TRANSFER_WORKER" in args[-1]:
            assert "-i" in args
            if self.failure == "existing_destination":
                return self.result(args, returncode=20, stderr=SECRET)
            if self.failure == "transfer":
                self.destination = b"partial synthetic destination"
                return self.result(args, returncode=21, stderr=SECRET)
            if self.failure == "destination_path_error":
                return self.result(args, returncode=23, stderr=SECRET)
            self.destination = kwargs["input"]
            return self.result(args, stdout=b'{"status":"TRANSFERRED"}\n')
        if args[1] == "run" and "app.mcp_auth" in args:
            source = json.loads(self.destination)
            status = "RENEWABLE_STATE_PRESENT"
            generation = source["generation"]
            returncode = 0
            if self.failure == "destination_validation":
                returncode = 1
            elif self.failure == "zero_exit_without_renewable":
                status = "MCP_AUTH_UNAVAILABLE"
            elif self.failure == "generation_mismatch":
                generation = str(uuid4())
            payload = {
                "status": status,
                "generation": generation,
                "live_validity": "UNVERIFIED",
            }
            return self.result(args, returncode=returncode, stdout=json.dumps(payload).encode())
        if args[1] == "run" and "OAUTH_HANDOFF_VERIFY_WORKER" in args[-1]:
            assert "-i" in args
            if self.failure == "content_validation":
                return self.result(args, returncode=22, stderr=SECRET)
            assert kwargs["input"] == self.destination
            payload = {
                "status": "DESTINATION_CONTENT_VERIFIED",
                "content_match": True,
                "private_modes": True,
                "runtime_owner": True,
            }
            return self.result(args, stdout=json.dumps(payload).encode())
        raise AssertionError(f"Unexpected command: {args}")


def test_success_preserves_exact_state_and_targets_explicit_project(
    tmp_path, handoff_module, monkeypatch
):
    source, generation = source_state(tmp_path, directory="finary-mcp-bootstrap.with spaces;$x")
    original = source.read_bytes()
    runner = FakeRunner()
    elsewhere = tmp_path / "caller cwd; with spaces"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    outcome = handoff_module.handoff(
        source, "synthetic-project", cleanup_source=False, runner=runner
    )

    assert outcome == {
        "status": "OAUTH_STATE_HANDOFF_VERIFIED",
        "bridge": "STOPPED",
        "renewable_state": True,
        "generation_match": True,
        "source_cleanup": "RETAINED",
    }
    assert UUID(generation)
    assert source.read_bytes() == original
    assert runner.destination == original
    for args, kwargs in runner.calls:
        assert kwargs["cwd"] == ROOT
        assert str(source) not in args
        assert "synthetic-renewable-token" not in " ".join(args)
        if args[:2] == ["docker", "compose"]:
            assert args[args.index("-p") + 1] == "synthetic-project"
            assert Path(args[args.index("-f") + 1]) == ROOT / "docker-compose.yml"
        if args[:2] == ["docker", "run"]:
            assert args[args.index("--network") + 1] == "none"


def test_successful_requested_cleanup_removes_only_staging_files(tmp_path, handoff_module):
    source, _ = source_state(tmp_path)
    original = source.read_bytes()
    runner = FakeRunner()

    outcome = handoff_module.handoff(
        source, "synthetic-cleanup", cleanup_source=True, runner=runner
    )

    assert outcome["source_cleanup"] == "REMOVED"
    assert runner.destination == original
    assert not source.parent.exists()


@pytest.mark.parametrize(
    ("case", "mutate"),
    [
        ("missing", lambda path: path.unlink()),
        ("directory_mode", lambda path: path.parent.chmod(0o755)),
        ("file_mode", lambda path: path.chmod(0o644)),
        ("malformed", lambda path: path.write_text("{synthetic-secret-marker")),
        ("invalid_issuer", lambda path: _rewrite(path, issuer="https://invalid.example")),
        ("missing_renewable", lambda path: _rewrite(path, refresh_token=None)),
        ("empty_generation", lambda path: _rewrite(path, generation="")),
    ],
)
def test_invalid_sources_fail_before_docker_or_new_coordination_files(
    tmp_path, handoff_module, case, mutate
):
    source, _ = source_state(tmp_path)
    for suffix in (".lock", ".lease"):
        Path(str(source) + suffix).unlink(missing_ok=True)
    mutate(source)
    runner = FakeRunner()

    with pytest.raises(handoff_module.HandoffFailure) as failure:
        handoff_module.handoff(source, "synthetic-invalid", False, runner=runner)

    assert failure.value.code == "SOURCE_INVALID", case
    assert runner.calls == []
    assert not Path(str(source) + ".lock").exists()
    assert not Path(str(source) + ".lease").exists()


def _rewrite(path, **changes):
    value = json.loads(path.read_text())
    if "issuer" in changes:
        value["client"]["issuer"] = changes.pop("issuer")
    value.update(changes)
    path.write_text(json.dumps(value))
    path.chmod(0o600)


def test_symlink_and_nonregular_sources_are_rejected(tmp_path, handoff_module):
    target, _ = source_state(tmp_path / "symlink")
    link_parent = tmp_path / "finary-mcp-bootstrap.link"
    link_parent.mkdir(mode=0o700)
    link = link_parent / "oauth.json"
    link.symlink_to(target)
    parent_link = tmp_path / "finary-mcp-bootstrap.parent-link"
    parent_link.symlink_to(target.parent, target_is_directory=True)
    fifo_parent = tmp_path / "finary-mcp-bootstrap.fifo"
    fifo_parent.mkdir(mode=0o700)
    fifo = fifo_parent / "oauth.json"
    os.mkfifo(fifo, mode=0o600)

    for source in (link, parent_link / "oauth.json", fifo):
        runner = FakeRunner()
        with pytest.raises(handoff_module.HandoffFailure) as failure:
            handoff_module.handoff(source, "synthetic-invalid", False, runner=runner)
        assert failure.value.code == "SOURCE_INVALID"
        assert runner.calls == []


def test_wrong_source_owner_is_rejected_before_docker(tmp_path, handoff_module, monkeypatch):
    source, _ = source_state(tmp_path)
    actual = auth.os.getuid()
    monkeypatch.setattr(auth.os, "getuid", lambda: actual + 1)
    runner = FakeRunner()

    with pytest.raises(handoff_module.HandoffFailure) as failure:
        handoff_module.handoff(source, "synthetic-owner", False, runner=runner)

    assert failure.value.code == "SOURCE_INVALID"
    assert runner.calls == []


@pytest.mark.parametrize("kind", ["wrong_mode", "symlink", "nonregular"])
def test_invalid_existing_coordination_file_is_rejected_before_new_files(
    tmp_path, handoff_module, kind
):
    source, _ = source_state(tmp_path)
    lease = Path(str(source) + ".lease")
    if kind == "wrong_mode":
        lease.touch(mode=0o600)
        lease.chmod(0o644)
    elif kind == "symlink":
        lease.symlink_to(source)
    else:
        os.mkfifo(lease, mode=0o600)
    runner = FakeRunner()

    with pytest.raises(handoff_module.HandoffFailure) as failure:
        handoff_module.handoff(source, "synthetic-coordination", False, runner=runner)

    assert failure.value.code == "SOURCE_INVALID"
    assert runner.calls == []
    assert not Path(str(source) + ".lock").exists()


def test_active_source_lease_is_rejected_without_destination_mutation(
    tmp_path, handoff_module, monkeypatch
):
    import fcntl

    source, _ = source_state(tmp_path)
    lease = Path(str(source) + ".lease")
    fd = os.open(lease, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

    async def immediate(_delay):
        return None

    monkeypatch.setattr(auth.asyncio, "sleep", immediate)
    runner = FakeRunner()
    try:
        with pytest.raises(handoff_module.HandoffFailure) as failure:
            handoff_module.handoff(source, "synthetic-active", False, runner=runner)
    finally:
        os.close(fd)

    assert failure.value.code == "SOURCE_ACTIVE"
    assert runner.destination is None


@pytest.mark.parametrize(
    ("fault", "code", "destination", "bridge"),
    [
        ("docker_unavailable", "DOCKER_UNAVAILABLE", None, "UNVERIFIED"),
        ("non_root_service", "COMPOSE_CONFIGURATION_INVALID", None, "UNVERIFIED"),
        ("shared_volume", "COMPOSE_CONFIGURATION_INVALID", None, "UNVERIFIED"),
        ("running", "DESTINATION_BRIDGE_RUNNING", None, "RUNNING"),
        ("invalid_status", "DESTINATION_STATUS_UNVERIFIED", None, "UNVERIFIED"),
        ("non_root_image", "DESTINATION_RUNTIME_UNSUPPORTED", None, "STOPPED"),
        ("destination_creation", "DESTINATION_CREATION_FAILED", None, "STOPPED"),
        ("wrong_volume_labels", "DESTINATION_CREATION_FAILED", None, "STOPPED"),
        ("destination_path_error", "DESTINATION_CREATION_FAILED", None, "STOPPED"),
        ("transfer", "DESTINATION_TRANSFER_FAILED", b"partial synthetic destination", "STOPPED"),
        ("destination_validation", "DESTINATION_VALIDATION_FAILED", "exact", "STOPPED"),
        ("zero_exit_without_renewable", "DESTINATION_VALIDATION_FAILED", "exact", "STOPPED"),
        ("generation_mismatch", "DESTINATION_GENERATION_MISMATCH", "exact", "STOPPED"),
        ("content_validation", "DESTINATION_VALIDATION_FAILED", "exact", "STOPPED"),
    ],
)
def test_failures_retain_source_and_report_exact_partial_destination(
    tmp_path, handoff_module, fault, code, destination, bridge
):
    source, _ = source_state(tmp_path)
    original = source.read_bytes()
    runner = FakeRunner(failure=fault)

    with pytest.raises(handoff_module.HandoffFailure) as failure:
        handoff_module.handoff(source, "synthetic-failure", True, runner=runner)

    assert failure.value.code == code
    assert source.read_bytes() == original
    expected = original if destination == "exact" else destination
    assert runner.destination == expected
    payload = handoff_module._failure_payload(failure.value)
    assert payload == {
        "status": "OAUTH_STATE_HANDOFF_FAILED",
        "reason": code,
        "bridge": bridge,
        "source_cleanup": "NOT_ATTEMPTED",
        "action": (
            "Keep the bridge stopped and inspect the destination and original staging state; "
            "do not overwrite or automatically retry."
            if failure.value.destination_touched
            else "Correct the prerequisite and retry with the original staging state."
        ),
    }


@pytest.mark.parametrize("state", ["paused", "restarting", "removing", "dead"])
def test_non_stopped_bridge_states_are_rejected(tmp_path, handoff_module, state):
    source, _ = source_state(tmp_path)
    runner = FakeRunner(failure=state)

    with pytest.raises(handoff_module.HandoffFailure) as failure:
        handoff_module.handoff(source, "synthetic-active-state", False, runner=runner)

    assert failure.value.code == "DESTINATION_BRIDGE_NOT_STOPPED"
    assert failure.value.bridge_state == "NOT_STOPPED"
    assert runner.destination is None


def test_source_changed_after_preflight_is_invalid_not_active(
    tmp_path, handoff_module, monkeypatch
):
    source, _ = source_state(tmp_path)
    runner = FakeRunner()
    real_require_stopped = handoff_module.DockerDestination.require_stopped
    calls = 0

    def stop_then_corrupt(destination):
        nonlocal calls
        calls += 1
        real_require_stopped(destination)
        if calls == 1:
            source.write_text("{synthetic-invalid-state")
            source.chmod(0o600)

    monkeypatch.setattr(
        handoff_module.DockerDestination, "require_stopped", stop_then_corrupt
    )

    with pytest.raises(handoff_module.HandoffFailure) as failure:
        handoff_module.handoff(source, "synthetic-source-race", False, runner=runner)

    assert failure.value.code == "SOURCE_INVALID"
    assert failure.value.bridge_state == "STOPPED"
    assert runner.destination is None


def test_existing_destination_and_repeated_invocation_never_overwrite(tmp_path, handoff_module):
    source, _ = source_state(tmp_path)
    original = source.read_bytes()
    runner = FakeRunner()
    handoff_module.handoff(source, "synthetic-repeat", False, runner=runner)
    installed = runner.destination
    runner.failure = "existing_destination"
    runner.volume_exists = True

    with pytest.raises(handoff_module.HandoffFailure) as failure:
        handoff_module.handoff(source, "synthetic-repeat", False, runner=runner)

    assert failure.value.code == "DESTINATION_EXISTS"
    assert source.read_bytes() == original
    assert runner.destination == installed


def test_cleanup_failure_is_partial_success_with_verified_destination(
    tmp_path, handoff_module, monkeypatch
):
    source, _ = source_state(tmp_path)
    original = source.read_bytes()
    runner = FakeRunner()
    real_unlink = Path.unlink

    def fail_lock(path, *args, **kwargs):
        if str(path).endswith(".lock"):
            raise PermissionError("synthetic-secret-marker")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_lock)

    with pytest.raises(handoff_module.HandoffFailure) as failure:
        handoff_module.handoff(source, "synthetic-cleanup-failure", True, runner=runner)

    assert failure.value.code == "SOURCE_CLEANUP_FAILED"
    assert failure.value.verified is True
    assert not source.exists()
    assert Path(str(source) + ".lock").is_file()
    assert Path(str(source) + ".lease").is_file()
    assert runner.destination == original
    assert handoff_module._failure_payload(failure.value) == {
        "status": "OAUTH_STATE_HANDOFF_VERIFIED_CLEANUP_FAILED",
        "reason": "SOURCE_CLEANUP_FAILED",
        "bridge": "STOPPED",
        "destination_verified": True,
        "source_cleanup": "FAILED",
        "action": "Inspect only the designated staging directory; do not repeat the handoff.",
    }


def test_cleanup_revalidation_failure_is_reported_after_verified_transfer(
    tmp_path, handoff_module, monkeypatch
):
    source, _ = source_state(tmp_path)
    original = source.read_bytes()
    runner = FakeRunner()
    real_preflight = handoff_module._preflight_cleanup
    calls = 0

    def change_after_transfer(path):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise handoff_module.HandoffFailure("SOURCE_CLEANUP_UNSAFE")
        real_preflight(path)

    monkeypatch.setattr(handoff_module, "_preflight_cleanup", change_after_transfer)

    with pytest.raises(handoff_module.HandoffFailure) as failure:
        handoff_module.handoff(source, "synthetic-cleanup-race", True, runner=runner)

    assert failure.value.code == "SOURCE_CLEANUP_FAILED"
    assert failure.value.verified is True
    assert source.read_bytes() == original
    assert runner.destination == original


def test_cleanup_rejects_source_changed_after_destination_verification(
    tmp_path, handoff_module, monkeypatch
):
    source, _ = source_state(tmp_path)
    original = source.read_bytes()
    runner = FakeRunner()
    real_validate = handoff_module.DockerDestination.validate

    def validate_then_replace(destination, content, generation):
        real_validate(destination, content, generation)
        _rewrite(source, generation=str(uuid4()))

    monkeypatch.setattr(handoff_module.DockerDestination, "validate", validate_then_replace)

    with pytest.raises(handoff_module.HandoffFailure) as failure:
        handoff_module.handoff(source, "synthetic-source-change", True, runner=runner)

    assert failure.value.code == "SOURCE_CLEANUP_FAILED"
    assert failure.value.verified is True
    assert source.read_bytes() != original
    assert runner.destination == original


def test_cleanup_keeps_source_lease_held_until_directory_removal(
    tmp_path, handoff_module, monkeypatch
):
    source, _ = source_state(tmp_path)
    lease = Path(str(source) + ".lease")
    runner = FakeRunner()
    real_cleanup = handoff_module._cleanup_source

    def probe_then_cleanup(store, content, generation, lease_fd):
        probe = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import fcntl, os, sys; "
                    "fd=os.open(sys.argv[1], os.O_RDWR); "
                    "result=0; "
                    "\ntry: fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB); result=1"
                    "\nexcept BlockingIOError: pass"
                    "\nfinally: os.close(fd)"
                    "\nraise SystemExit(result)"
                ),
                str(lease),
            ],
            check=False,
            capture_output=True,
            timeout=10,
        )
        assert probe.returncode == 0
        real_cleanup(store, content, generation, lease_fd)

    monkeypatch.setattr(handoff_module, "_cleanup_source", probe_then_cleanup)

    outcome = handoff_module.handoff(
        source, "synthetic-continuous-lease", True, runner=runner
    )

    assert outcome["source_cleanup"] == "REMOVED"
    assert not source.parent.exists()


def test_cli_help_and_sanitized_failure_output(tmp_path, handoff_module, monkeypatch, capsys):
    help_result = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert help_result.returncode == 0
    assert "fresh" in help_result.stdout.lower()
    assert "migration" in help_result.stdout.lower()
    source, _ = source_state(tmp_path)
    runner = FakeRunner(failure="destination_creation")
    monkeypatch.setattr(handoff_module.subprocess, "run", runner)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(SCRIPT),
            "--source",
            str(source),
            "--project-name",
            "synthetic-cli",
        ],
    )

    with pytest.raises(SystemExit) as exited:
        handoff_module.main()

    captured = capsys.readouterr()
    assert exited.value.code != 0
    assert captured.out == ""
    payload = json.loads(captured.err)
    assert payload["status"] == "OAUTH_STATE_HANDOFF_FAILED"
    assert payload["reason"] == "DESTINATION_CREATION_FAILED"
    assert "synthetic-secret-marker" not in captured.out + captured.err


def test_project_name_is_rejected_before_docker(tmp_path, handoff_module):
    source, _ = source_state(tmp_path)
    runner = FakeRunner()
    with pytest.raises(handoff_module.HandoffFailure) as failure:
        handoff_module.handoff(source, "../wrong project;$x", False, runner=runner)
    assert failure.value.code == "PROJECT_NAME_INVALID"
    assert runner.calls == []
