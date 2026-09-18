"""Bounded real-image regression for rootful Linux operator ownership."""

import asyncio
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from mcp_auth_peer import AuthPeer, consent
from mcp_oauth_handoff import assert_private, renew

from app.mcp_auth import CALLBACK, ISSUER, OAuthState, OAuthStore

ROOT = Path(__file__).parents[2]
HANDOFF = ROOT / "scripts/handoff-mcp-oauth-state.py"


def test_rootful_linux_host_container_host_handoff(tmp_path):
    def unavailable(reason):
        if os.getenv("FINARY_REQUIRE_OAUTH_DOCKER") == "1":
            pytest.fail(reason)
        pytest.skip(reason)

    if sys.platform != "linux" or os.getuid() == 0 or not shutil.which("docker"):
        unavailable("Requires a non-root Linux operator and rootful Docker")

    def run(args, *, timeout=60, env=None, check=True):
        return subprocess.run(
            args, cwd=ROOT, env=env, capture_output=True, text=True,
            timeout=timeout, check=check,
        )

    info = run(["docker", "info", "--format", "{{json .}}"], check=False)
    if info.returncode:
        unavailable("Docker daemon is unavailable")
    details = json.loads(info.stdout)
    if any("rootless" in option or "userns" in option for option in details["SecurityOptions"]):
        unavailable("Requires rootful Docker without user-namespace remapping")

    store = OAuthStore(tmp_path / "synthetic operator state" / "oauth.json")
    asyncio.run(consent(store, AuthPeer()))
    assert_private(store)
    env = {
        "PATH": os.environ.get("PATH", os.defpath), "COMPOSE_ENV_FILES": "/dev/null",
        "FINARY_MCP_TEST_DIR": str(store.path.parent),
        "FINARY_MCP_CANDIDATE_UID": str(os.getuid()),
        "FINARY_MCP_CANDIDATE_GID": str(os.getgid()),
        "FINARY_MCP_CANDIDATE_API_KEY": "synthetic-key",
        "FINARY_MCP_CANDIDATE_WORKBOOK_ID": "synthetic-book",
    }
    run([sys.executable, "scripts/validate-mcp-candidate.py"], env=env)
    project = "finary-ownership-" + uuid4().hex
    compose = ["docker", "compose", "--env-file", "/dev/null", "-p", project,
               "-f", "docker-compose.mcp-test.yml"]
    config = json.loads(run([*compose, "config", "--format", "json"], env=env).stdout)
    service = config["services"]["finary-bridge"]
    mount = service["volumes"][0]
    assert service["user"] == f"{os.getuid()}:{os.getgid()}"
    # Compose versions may omit the false boolean in resolved JSON.
    assert mount["type"] == "bind"
    assert mount.get("bind", {}).get("create_host_path", False) is False
    assert "create_host_path: false" in (ROOT / "docker-compose.mcp-test.yml").read_text()
    assert mount["source"] == str(store.path.parent)
    fixtures = tmp_path / "fixtures"
    for relative in (
        "finary-bridge/tests/mcp_oauth_handoff.py",
        "finary-bridge/tests/mcp_auth_peer.py",
        "finary-bridge/tests/mcp_wire.py",
        "finary-bridge/tests/mcp_artifacts.py",
        "docs/finary-mcp-contract.json",
        "docs/google-sheets-schema.json",
        "n8n/workflows/finary-mcp-sync.json",
    ):
        destination = fixtures / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, destination)
    shutil.copytree(ROOT / "finary-bridge/tests/fixtures/finary-mcp",
                    fixtures / "finary-bridge/tests/fixtures/finary-mcp")
    image = project + ":test"
    container = project + "-bridge"
    try:
        build = service["build"]
        run(["docker", "build", "-t", image, "-f",
             str(Path(build["context"]) / build.get("dockerfile", "Dockerfile")),
             build["context"]], timeout=300)

        default_user = run(["docker", "image", "inspect", image,
                            "--format", "{{.Config.User}}"]).stdout.strip()
        assert default_user in ("", "0", "root")

        def container_run(identity, action):
            result = run([
                "docker", "run", "--rm", "--name", container, "--network", "none",
                *(["--user", identity] if identity is not None else []),
                "--mount", f"type=bind,source={mount['source']},target={mount['target']}",
                "--mount", f"type=bind,source={fixtures},target=/fixture,readonly",
                "-e", "PYTHONPATH=/fixture/finary-bridge/tests",
                "-e", "FINARY_MCP_STATE_PATH=" + service["environment"]["FINARY_MCP_STATE_PATH"],
                image, "python", "/fixture/finary-bridge/tests/mcp_oauth_handoff.py", action,
            ])
            assert result.stdout.strip() == "SYNTHETIC_HANDOFF_VALIDATED"

        original = store.path.read_bytes()
        # This is the original image default: root against non-root host state.
        container_run(None, "reject")
        assert store.path.read_bytes() == original
        assert_private(store)
        # Closed host sessions permit container creation of both coordination files.
        for suffix in (".lock", ".lease"):
            Path(str(store.path) + suffix).unlink()
        inode = store.path.stat().st_ino
        container_run(service["user"], "renew")
        assert store.path.stat().st_ino != inode
        assert_private(store)
        assert store.read().refresh_token == "synthetic-renewable-2"
        renew(store)
        assert store.read().refresh_token == "synthetic-renewable-3"
    finally:
        run(["docker", "rm", "-f", container], check=False)
        run(["docker", "image", "rm", "-f", image], check=False)


def test_rootful_linux_fresh_install_helper_uses_production_volume(tmp_path):
    def unavailable(reason):
        if os.getenv("FINARY_REQUIRE_OAUTH_DOCKER") == "1":
            pytest.fail(reason)
        pytest.skip(reason)

    if sys.platform != "linux" or not shutil.which("docker"):
        unavailable("Requires rootful Linux Docker")

    def run(args, *, timeout=60, env=None, check=True, input=None):
        return subprocess.run(
            args,
            cwd=ROOT,
            env=env,
            input=input,
            capture_output=True,
            timeout=timeout,
            check=check,
        )

    info = run(["docker", "info", "--format", "{{json .}}"], check=False)
    if info.returncode:
        unavailable("Docker daemon is unavailable")
    details = json.loads(info.stdout)
    if any(
        "rootless" in option or "userns" in option for option in details["SecurityOptions"]
    ):
        unavailable("Requires rootful Docker without user-namespace remapping")

    source_directory = tmp_path / "finary-mcp-bootstrap.synthetic-docker"
    store = OAuthStore(source_directory / "oauth.json")
    state = store.replace(
        "",
        OAuthState(
            "",
            {
                "client_id": "synthetic-local-client",
                "issuer": ISSUER,
                "redirect_uris": [CALLBACK],
                "token_endpoint_auth_method": "none",
            },
            "synthetic-renewable-docker",
            "openid offline_access",
        ),
    )
    original = store.path.read_bytes()
    project = "finary-handoff-" + uuid4().hex
    volume = project + "_finary_mcp_data"
    compose = [
        "docker",
        "compose",
        "--project-directory",
        str(ROOT),
        "-f",
        str(ROOT / "docker-compose.yml"),
        "-p",
        project,
    ]
    env = {
        "PATH": os.environ.get("PATH", os.defpath),
        "COMPOSE_ENV_FILES": "/dev/null",
    }
    repository = project + "-finary-bridge"
    try:
        result = run(
            [
                sys.executable,
                str(HANDOFF),
                "--source",
                str(store.path),
                "--project-name",
                project,
                "--cleanup-source",
            ],
            timeout=360,
            env=env,
        )
        assert json.loads(result.stdout) == {
            "bridge": "STOPPED",
            "generation_match": True,
            "renewable_state": True,
            "source_cleanup": "REMOVED",
            "status": "OAUTH_STATE_HANDOFF_VERIFIED",
        }
        assert result.stderr == b""
        assert not source_directory.exists()
        stopped = run(
            [*compose, "ps", "--status", "running", "--quiet", "finary-bridge"], env=env
        )
        assert stopped.stdout == b""
        image = run(
            ["docker", "image", "inspect", repository, "--format", "{{.Id}}"], env=env
        ).stdout.strip()
        probe = r'''
import hmac
import json
import os
import stat
import sys
from pathlib import Path

directory = Path("/var/lib/finary-mcp/state")
state_path = directory / "oauth.json"
expected = sys.stdin.buffer.read()
actual = state_path.read_bytes()
directory_info = directory.stat()
file_info = state_path.stat()
value = json.loads(actual)
assert hmac.compare_digest(actual, expected)
assert value["generation"] == sys.argv[1]
assert value["refresh_token"] == "synthetic-renewable-docker"
assert (directory_info.st_uid, directory_info.st_gid) == (0, 0)
assert (file_info.st_uid, file_info.st_gid) == (0, 0)
assert stat.S_IMODE(directory_info.st_mode) == 0o700
assert stat.S_IMODE(file_info.st_mode) == 0o600
print("SYNTHETIC_PRODUCTION_VOLUME_HANDOFF_VALIDATED")
'''
        inspected = run(
            [
                "docker",
                "run",
                "--rm",
                "-i",
                "--network",
                "none",
                "--mount",
                f"type=volume,source={volume},target=/var/lib/finary-mcp",
                image.decode(),
                "python",
                "-c",
                probe,
                state.generation,
            ],
            input=original,
        )
        assert inspected.stdout.strip() == b"SYNTHETIC_PRODUCTION_VOLUME_HANDOFF_VALIDATED"
    finally:
        run(["docker", "volume", "rm", "-f", volume], check=False)
        run(["docker", "image", "rm", "-f", repository], check=False)
