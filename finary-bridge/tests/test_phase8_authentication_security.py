"""Regression checks for the Phase 8 accepted authentication boundary."""

from __future__ import annotations

import inspect
import json
from pathlib import Path

from app.finary_client import FinaryApiClient, FinaryCredentials

_BRIDGE_ROOT = Path(__file__).parents[1]
_REPOSITORY_ROOT = _BRIDGE_ROOT.parent


def test_adapter_has_no_stronger_credential_persistence_path() -> None:
    source = inspect.getsource(FinaryApiClient)

    for prohibited in (
        "pickle",
        "FINARY_TOTP_SECRET",
        "FINARY_BACKUP_CODE",
        "FINARY_REFRESH_TOKEN",
        "otpauth://",
    ):
        assert prohibited not in source


def test_no_totp_generator_or_persistent_auth_configuration_exists() -> None:
    credential_fields = set(FinaryCredentials.__dataclass_fields__)
    assert credential_fields == {"email", "password", "mfa_code"}

    environment_lines = {
        line.split("=", maxsplit=1)[0]
        for line in (_REPOSITORY_ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#") and "=" in line
    }
    assert environment_lines.isdisjoint(
        {
            "FINARY_TOTP_SECRET",
            "FINARY_BACKUP_CODE",
            "FINARY_SESSION_COOKIE",
            "FINARY_SESSION_TOKEN",
            "FINARY_REFRESH_TOKEN",
        }
    )

    project = (_BRIDGE_ROOT / "pyproject.toml").read_text(encoding="utf-8").lower()
    assert "pyotp" not in project


def test_finary_authentication_material_is_not_passed_to_n8n() -> None:
    compose = (_REPOSITORY_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    n8n_environment = compose.split("  n8n:", maxsplit=1)[1].split("    ports:", maxsplit=1)[0]

    for variable in (
        "FINARY_EMAIL",
        "FINARY_PASSWORD",
        "FINARY_MFA_CODE",
        "FINARY_TOTP_SECRET",
        "FINARY_SESSION_TOKEN",
    ):
        assert variable not in n8n_environment


def test_session_volume_is_mounted_only_into_bridge() -> None:
    compose = (_REPOSITORY_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    bridge_section = compose.split("  finary-bridge:", maxsplit=1)[1].split(
        "  schema-server:", maxsplit=1
    )[0]
    schema_section = compose.split("  schema-server:", maxsplit=1)[1].split("  n8n:", maxsplit=1)[0]
    n8n_section = compose.split("  n8n:", maxsplit=1)[1].split("networks:", maxsplit=1)[0]

    assert "finary_session_data:/var/lib/finary-session" in bridge_section
    assert "finary_session_data" not in schema_section
    assert "finary_session_data" not in n8n_section


def test_production_daily_workflow_remains_inactive() -> None:
    workflow = json.loads(
        (_REPOSITORY_ROOT / "n8n/workflows/finary-daily-sync.json").read_text(encoding="utf-8")
    )

    assert workflow["active"] is False


def test_phase8_decision_and_security_boundary_are_documented() -> None:
    investigation = (_REPOSITORY_ROOT / "docs/finary-authentication-investigation.md").read_text(
        encoding="utf-8"
    )

    assert "Outcome A: secure persisted Clerk session accepted" in investigation
    assert "Clerk session identifier" in investigation
    assert "production `__client` cookie" in investigation
    assert "does not persist that JWT" in investigation
    assert "not backed up" in investigation
    assert "remaining production activation\ngates still apply" in investigation
