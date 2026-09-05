"""Credential-free structural checks for the canonical Compose stack."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).parents[2]
COMPOSE_PATH = ROOT / "docker-compose.yml"
DAILY_PATH = ROOT / "n8n" / "workflows" / "finary-daily-sync.json"

_SYNTHETIC_ENV = {
    "FINARY_BRIDGE_API_KEY": "test-bridge-key",
    "FINARY_BRIDGE_PORT": "8000",
    "FINARY_BRIDGE_URL": "http://finary-bridge:8000",
    "FINARY_EMAIL": "test@example.invalid",
    "FINARY_GOOGLE_SHEET_ID": "synthetic-workbook-id",
    "FINARY_MFA_CODE": "",
    "FINARY_PASSWORD": "synthetic-password",
    "FINARY_SCHEMA_URL": "http://schema-server/google-sheets-schema.json",
    "FINARY_SESSION_PATH": "/var/lib/finary-session/state/session.json",
    "N8N_ENCRYPTION_KEY": "synthetic-encryption-key-with-sufficient-length",
    "N8N_EXECUTIONS_TIMEOUT": "300",
    "N8N_EXECUTIONS_TIMEOUT_MAX": "300",
    "N8N_PORT": "5678",
    "TZ": "Europe/Paris",
}


def _compose_config() -> dict[str, Any]:
    if shutil.which("docker") is None:
        pytest.skip("Docker Compose is required for resolved topology validation")
    environment = {"PATH": os.environ.get("PATH", os.defpath), **_SYNTHETIC_ENV}
    completed = subprocess.run(  # noqa: S603
        [
            "docker",
            "compose",
            "--env-file",
            os.devnull,
            "--file",
            str(COMPOSE_PATH),
            "--project-name",
            "finary-compose-test",
            "config",
            "--format",
            "json",
        ],
        cwd=ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def _mount(service: dict[str, Any], target: str) -> dict[str, Any]:
    return next(volume for volume in service["volumes"] if volume["target"] == target)


def test_compose_declares_only_the_canonical_services_and_named_volumes() -> None:
    config = _compose_config()

    assert set(config["services"]) == {"finary-bridge", "n8n", "schema-server"}
    assert set(config["networks"]) == {"finary-stack"}
    assert set(config["volumes"]) == {"finary_session_data", "n8n_data"}
    assert all(
        set(service["networks"]) == {"finary-stack"} for service in config["services"].values()
    )


def test_state_volumes_are_persistent_and_strictly_isolated() -> None:
    services = _compose_config()["services"]
    bridge = services["finary-bridge"]
    n8n = services["n8n"]
    schema = services["schema-server"]

    assert _mount(bridge, "/var/lib/finary-session")["source"] == ("finary_session_data")
    assert _mount(n8n, "/home/node/.n8n")["source"] == "n8n_data"
    assert all(volume.get("source") != "n8n_data" for volume in bridge["volumes"])
    assert all(volume.get("source") != "finary_session_data" for volume in n8n["volumes"])
    assert all(volume["type"] != "volume" for volume in schema["volumes"])


def test_compose_exposure_and_internal_urls_are_local_only() -> None:
    services = _compose_config()["services"]
    bridge_port = services["finary-bridge"]["ports"][0]
    n8n_port = services["n8n"]["ports"][0]

    assert (bridge_port["host_ip"], bridge_port["published"], bridge_port["target"]) == (
        "127.0.0.1",
        "8000",
        8000,
    )
    assert (n8n_port["host_ip"], n8n_port["published"], n8n_port["target"]) == (
        "127.0.0.1",
        "5678",
        5678,
    )
    assert "ports" not in services["schema-server"]
    assert services["n8n"]["environment"]["FINARY_BRIDGE_URL"] == ("http://finary-bridge:8000")
    assert services["n8n"]["environment"]["FINARY_SCHEMA_URL"] == (
        "http://schema-server/google-sheets-schema.json"
    )


def test_images_schema_mount_and_operational_controls_are_pinned() -> None:
    services = _compose_config()["services"]
    n8n = services["n8n"]
    schema = services["schema-server"]

    assert n8n["image"].startswith("n8nio/n8n:2.35.5@sha256:")
    assert schema["image"].startswith("nginx:1.31.4@sha256:")
    schema_mount = _mount(schema, "/usr/share/nginx/html/google-sheets-schema.json")
    assert schema_mount["type"] == "bind"
    assert schema_mount["read_only"] is True
    assert schema_mount["source"] == str((ROOT / "docs" / "google-sheets-schema.json").resolve())
    assert n8n["restart"] == "unless-stopped"
    assert schema["restart"] == "unless-stopped"
    assert services["finary-bridge"]["restart"] == "unless-stopped"
    assert n8n["environment"]["EXECUTIONS_TIMEOUT"] == "300"
    assert n8n["environment"]["EXECUTIONS_TIMEOUT_MAX"] == "300"
    assert n8n["environment"]["N8N_BLOCK_ENV_ACCESS_IN_NODE"] == "false"
    assert n8n["environment"]["N8N_DIAGNOSTICS_ENABLED"] == "false"


def test_health_checks_and_startup_dependencies_are_preserved() -> None:
    services = _compose_config()["services"]

    for service in services.values():
        healthcheck = service["healthcheck"]
        assert healthcheck["test"][0] == "CMD"
        assert healthcheck.get("disable", False) is False
        assert healthcheck["interval"] == "10s"
        assert healthcheck["timeout"] == "3s"
        assert healthcheck["retries"] > 0
    assert "/health" in " ".join(services["finary-bridge"]["healthcheck"]["test"])
    assert "/healthz" in " ".join(services["n8n"]["healthcheck"]["test"])
    assert set(services["n8n"]["depends_on"]) == {"finary-bridge", "schema-server"}
    assert all(
        dependency["condition"] == "service_healthy"
        for dependency in services["n8n"]["depends_on"].values()
    )


def test_repository_configuration_contains_no_live_secret_or_credential_binding() -> None:
    compose = COMPOSE_PATH.read_text(encoding="utf-8")
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    workflows = "\n".join(
        path.read_text(encoding="utf-8") for path in (ROOT / "n8n" / "workflows").glob("*.json")
    )

    assert "FINARY_PASSWORD: ${FINARY_PASSWORD:-}" in compose
    assert "N8N_ENCRYPTION_KEY: ${N8N_ENCRYPTION_KEY:-}" in compose
    assert "FINARY_PASSWORD=\n" in example
    assert "N8N_ENCRYPTION_KEY=\n" in example
    assert '"credentials"' not in workflows


def test_canonical_daily_workflow_export_remains_inactive() -> None:
    workflow = json.loads(DAILY_PATH.read_text(encoding="utf-8"))

    assert workflow["name"] == "Finary - Daily Sync"
    assert workflow["active"] is False
    assert "30 7 * * *" in DAILY_PATH.read_text(encoding="utf-8")
