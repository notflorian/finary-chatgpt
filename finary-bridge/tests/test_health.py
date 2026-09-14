"""Local application metadata and installed-package version contract."""

import tomllib
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import SERVICE_VERSION
from app.main import app


def test_package_service_and_openapi_versions_agree():
    project = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text())
    with TestClient(app) as client:
        assert project["project"]["version"] == SERVICE_VERSION == "1.0.0"
        assert client.get("/openapi.json").json()["info"]["version"] == SERVICE_VERSION
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {
            "status": "ok", "service": "finary-bridge", "version": SERVICE_VERSION,
        }


def test_application_import_and_startup_without_operator_configuration(tmp_path):
    import os
    import subprocess
    import sys

    probe = '''
import socket
from unittest.mock import patch

def forbidden(*args, **kwargs):
    raise AssertionError("Unexpected network or OAuth access")

with patch.object(socket.socket, "connect", forbidden):
    from app import main, mcp_auth
    from fastapi.testclient import TestClient
    with (
        patch.object(main, "NativeMcpClient", forbidden),
        patch.object(mcp_auth, "OAuthStore", forbidden),
    ):
        with TestClient(main.app) as client:
            assert client.get("/health").status_code == 200
            assert client.get("/openapi.json").status_code == 200
'''
    subprocess.run(
        [sys.executable, "-I", "-c", probe], cwd=tmp_path,
        env={"PATH": os.environ.get("PATH", os.defpath)}, check=True,
        capture_output=True, text=True, timeout=30,
    )
