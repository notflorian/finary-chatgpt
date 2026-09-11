"""Opt-in structural acceptance using an explicitly isolated operator connection."""

import asyncio
import json
import os
from pathlib import Path

import pytest

from app.mcp_auth import OAuthStore, authorized_http
from app.mcp_client import NativeMcpClient
from app.services.mcp_snapshot_service import McpSnapshotService

pytestmark = pytest.mark.live


def test_isolated_native_collection_structure(capsys, monkeypatch):
    if (
        os.getenv("FINARY_MCP_LIVE_TEST") != "1"
        or os.getenv("FINARY_MCP_LIVE_ISOLATED_STATE") != "1"
    ):
        pytest.skip("Independent isolated MCP operator authorization is required")
    configured = os.getenv("FINARY_MCP_LIVE_STATE_PATH")
    if not configured:
        pytest.skip("An explicit isolated state path is required")
    store = OAuthStore(Path(configured))
    client = NativeMcpClient(lambda: authorized_http(store=store))

    async def verify():
        async with client.session(("get_portfolio_overview", "accounts", "holdings")) as session:
            revision = session.client.protocol_version
        result = await McpSnapshotService(client).snapshot()
        assert result.schema_version == "3.0"
        assert result.provenance.provider == "finary_official_mcp"
        return revision

    report = None
    if os.getenv("FINARY_MCP_LIVE_DIAGNOSTICS") == "1":
        from mcp_live_diagnostics import install_diagnostics

        report = install_diagnostics(monkeypatch)
    try:
        revision = asyncio.run(verify())
    except Exception as error:
        if report is not None:
            with capsys.disabled():
                report(error)
        raise
    with capsys.disabled():
        print(
            json.dumps({"status": "STRUCTURAL_COLLECTION_VALIDATED", "protocol_revision": revision})
        )


def test_isolated_natural_expiry_renewal(capsys):
    """Retain one OAuth session across natural expiry without extending a collection."""
    from contextlib import asynccontextmanager
    from time import time

    from mcp_live_expiry import wait_for_expiry

    if any(
        os.getenv(name) != "1"
        for name in (
            "FINARY_MCP_LIVE_TEST",
            "FINARY_MCP_LIVE_ISOLATED_STATE",
            "FINARY_MCP_LIVE_EXPIRY_TEST",
        )
    ):
        pytest.skip("Explicit isolated natural-expiry acceptance is required")
    configured = os.getenv("FINARY_MCP_LIVE_STATE_PATH")
    if not configured:
        pytest.skip("An explicit isolated state path is required")
    max_wait = int(os.getenv("FINARY_MCP_LIVE_EXPIRY_MAX_WAIT_SECONDS", "7200"))
    if not 0 < max_wait <= 86400:
        pytest.fail("MCP_EXPIRY_INVALID_WAIT_BOUND", pytrace=False)

    def emit(status, **fields):
        with capsys.disabled():
            print(json.dumps({"status": status, **fields}), flush=True)

    async def verify():
        async with authorized_http(store=OAuthStore(Path(configured))) as http:

            @asynccontextmanager
            async def reuse_oauth():
                yield http

            client = NativeMcpClient(reuse_oauth)
            service = McpSnapshotService(client)
            before = await service.snapshot()
            assert before.schema_version == "3.0"
            context = http.auth.context
            expiry = context.token_expiry_time
            generation = context.storage.state.generation
            assert context.is_token_valid()
            emit("INITIAL_COLLECTION_VALIDATED")
            await wait_for_expiry(
                expiry,
                max_wait,
                lambda remaining: emit("WAITING_FOR_NATURAL_EXPIRY", remaining_seconds=remaining),
            )
            assert not context.is_token_valid()
            emit("NATURAL_EXPIRY_OBSERVED")
            after = await service.snapshot()
            assert after.schema_version == "3.0"
            assert context.storage.state.generation != generation
            assert context.token_expiry_time > expiry
            assert context.token_expiry_time > time() and context.is_token_valid()
            assert after.observation_id != before.observation_id
            emit("NATURAL_EXPIRY_RENEWAL_VALIDATED", same_oauth_session=True)

    try:
        asyncio.run(verify())
    except Exception:
        pytest.fail("MCP_NATURAL_EXPIRY_ACCEPTANCE_FAILED", pytrace=False)
