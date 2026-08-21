"""Explicit opt-in sanitized restart verification for persisted Clerk state."""

from __future__ import annotations

import getpass
import os
from pathlib import Path

import pytest

from app.finary_client import FinaryApiClient
from app.finary_session_store import FileFinarySessionStore

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.getenv("FINARY_LIVE_SESSION_TEST") != "1",
        reason="Set FINARY_LIVE_SESSION_TEST=1 to verify persisted-session reuse",
    ),
]


def test_live_session_survives_two_fresh_clients() -> None:
    """Bootstrap once, then refresh from two clients without another MFA code."""

    session_path = os.getenv("FINARY_SESSION_PATH", "").strip()
    if not session_path or not Path(session_path).is_absolute():
        pytest.fail("FINARY_SESSION_PATH must be an absolute protected local path")
    store = FileFinarySessionStore(session_path)
    if store.load() is not None:
        pytest.fail("Use a new empty FINARY_SESSION_PATH for bootstrap verification")

    environment = dict(os.environ)
    environment.pop("FINARY_MFA_CODE", None)
    bootstrap_client = FinaryApiClient.from_environment(
        environment=environment,
        second_factor_code_provider=_prompt_second_factor_code,
    )
    bootstrap_client.authenticate()
    bootstrap_client.get_accounts()
    assert store.load() is not None
    print("PERSISTED SESSION BOOTSTRAP VERIFIED")

    restart_client = FinaryApiClient.from_environment(environment=environment)
    restart_client.authenticate()
    restart_client.get_accounts()
    assert store.load() is not None
    print("RESTART SESSION REUSE VERIFIED")
    print("SESSION REFRESH VERIFIED")

    second_restart_client = FinaryApiClient.from_environment(environment=environment)
    second_restart_client.authenticate()
    second_restart_client.get_accounts()
    assert store.load() is not None
    print("SECOND RESTART SESSION REUSE VERIFIED")


def _prompt_second_factor_code(strategy: str) -> str:
    description = "email" if strategy == "email_code" else strategy
    return getpass.getpass(f"Enter the one-time Finary {description} code: ")
