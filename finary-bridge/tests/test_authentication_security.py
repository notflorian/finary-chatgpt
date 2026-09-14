"""Package and configuration exclude private authentication and isolate OAuth."""

import ast
import json
import tomllib
from pathlib import Path

ROOT = Path(__file__).parents[2]
OBSOLETE = {
    "FINARY_EMAIL", "FINARY_PASSWORD", "FINARY_MFA_CODE", "FINARY_SESSION_PATH", "FINARY_PROVIDER",
}


def test_supported_configuration_has_no_private_authentication():
    for name in (".env.example", "docker-compose.yml", "docker-compose.mcp-test.yml"):
        text = (ROOT / name).read_text()
        assert all(variable not in text for variable in OBSOLETE)
        assert "finary_session_data" not in text
    compose = (ROOT / "docker-compose.yml").read_text()
    bridge, downstream = compose.split("  schema-server:", 1)
    assert "finary_mcp_data:/var/lib/finary-mcp" in bridge
    assert "FINARY_MCP_STATE_PATH" in bridge
    assert "FINARY_MCP_STATE_PATH" not in downstream
    assert "/var/lib/finary-mcp" not in downstream
    assert "/home/node/.n8n" not in bridge


def test_package_has_only_supported_modules_and_dependencies():
    bridge = ROOT / "finary-bridge"
    project = tomllib.loads((bridge / "pyproject.toml").read_text())["project"]
    requirements = " ".join(project["dependencies"]).lower()
    assert "curl-cffi" not in requirements and "finary_uapi" not in requirements
    for name in ("finary_client.py", "finary_session_store.py", "normalizer.py",
                 "models.py", "services/snapshot_service.py"):
        assert not (bridge / "app" / name).exists()
    for path in (bridge / "app").rglob("*.py"):
        source = path.read_text()
        ast.parse(source)
        assert all(variable not in source for variable in OBSOLETE)
        assert "curl_cffi" not in source


def test_workflow_exports_remain_inactive_and_credential_free():
    for path in (ROOT / "n8n/workflows").glob("*.json"):
        source = path.read_text()
        assert json.loads(source)["active"] is False
        assert '"credentials"' not in source
