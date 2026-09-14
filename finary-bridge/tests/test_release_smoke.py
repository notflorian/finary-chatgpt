"""Exercise the release smoke's observable no-access guards against real boundaries."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]


@pytest.mark.parametrize("operation,expected", [
    ("from app.mcp_client import NativeMcpClient; NativeMcpClient()", "NativeMcpClient.__init__"),
    ("from app.mcp_auth import OAuthStore; OAuthStore(state / 'oauth.json')",
     "OAuthStore.__init__"),
    ("(state / 'oauth.json').read_bytes()", "OAuth state file access"),
    ("socket.socket().connect(('127.0.0.1', 9))", "socket.connect"),
    ("socket.getaddrinfo('synthetic.invalid', 443)", "socket.getaddrinfo"),
    ("socket.socket(socket.AF_INET, socket.SOCK_DGRAM).sendto(b'x', ('127.0.0.1', 9))",
     "socket.sendto"),
])
def test_attempts_are_observable_even_when_caught(tmp_path, operation, expected):
    marker = tmp_path / "attempts.log"
    state = tmp_path / "synthetic-state"
    state.mkdir()
    code = f'''
import runpy, socket
from pathlib import Path
smoke = runpy.run_path({str(ROOT / "scripts/smoke-installed-product.py")!r})
state = Path({str(state)!r})
smoke['guards'](Path({str(marker)!r}), state)
try:
    exec({operation!r})
except AssertionError:
    pass
else:
    raise AssertionError('Guard failed to reject access')
'''
    subprocess.run([sys.executable, "-I", "-c", code], cwd=tmp_path,
                   env={"PATH": os.environ.get("PATH", os.defpath)}, check=True, timeout=30)
    assert expected in marker.read_text()
    assert list(state.iterdir()) == []


def test_compose_builds_resolve_the_same_explicit_dockerfile(tmp_path):
    if not shutil.which("docker"):
        pytest.skip("Docker Compose is required for resolved build validation")
    environment = {
        "PATH": os.environ.get("PATH", os.defpath), "COMPOSE_ENV_FILES": os.devnull,
        "FINARY_MCP_TEST_DIR": str(tmp_path), "FINARY_MCP_CANDIDATE_UID": "1001",
        "FINARY_MCP_CANDIDATE_GID": "1001", "FINARY_MCP_CANDIDATE_API_KEY": "synthetic-key",
        "FINARY_MCP_CANDIDATE_WORKBOOK_ID": "synthetic-book",
    }
    builds = []
    for filename in ("docker-compose.yml", "docker-compose.mcp-test.yml"):
        result = subprocess.run(
            ["docker", "compose", "--env-file", os.devnull, "-f", str(ROOT / filename),
             "config", "--format", "json"], env=environment,
            capture_output=True, text=True, check=True, timeout=30,
        )
        builds.append(json.loads(result.stdout)["services"]["finary-bridge"]["build"])
    assert builds[0] == builds[1]
    assert builds[0]["context"] == str(ROOT)
    assert builds[0]["dockerfile"] == "finary-bridge/Dockerfile"
