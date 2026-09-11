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


def test_isolated_native_collection_structure(capsys):
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

    revision = asyncio.run(verify())
    with capsys.disabled():
        print(
            json.dumps({"status": "STRUCTURAL_COLLECTION_VALIDATED", "protocol_revision": revision})
        )
