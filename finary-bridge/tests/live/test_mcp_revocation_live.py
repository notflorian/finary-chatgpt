"""Explicitly destructive acceptance for a newly authorized disposable OAuth grant."""

import asyncio
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

import httpx2
import pytest
from mcp_live_revocation import access_outcome, refresh_outcome

from app.mcp_auth import OAuthStore, authorized_http, public_metadata, revoke_command
from app.mcp_client import MCP_URL, BoundedTransport, NativeMcpClient

pytestmark = pytest.mark.live


def test_disposable_server_revocation(capsys):
    if any(
        os.getenv(name) != "1"
        for name in (
            "FINARY_MCP_LIVE_TEST",
            "FINARY_MCP_LIVE_ISOLATED_STATE",
            "FINARY_MCP_LIVE_REVOKE_DISPOSABLE",
        )
    ):
        pytest.skip("Explicit revocation of a dedicated disposable connection is required")
    configured = os.getenv("FINARY_MCP_REVOCATION_TEST_DIR")
    if not configured:
        pytest.skip("A separate disposable revocation directory is required")
    directory = Path(configured).resolve()
    if not directory.name.startswith("finary-mcp-revocation."):
        pytest.fail("MCP_REVOCATION_REQUIRES_DEDICATED_DIRECTORY", pytrace=False)
    existing = os.getenv("FINARY_MCP_TEST_DIR")
    if existing and directory == Path(existing).resolve():
        pytest.fail("MCP_REVOCATION_STATE_MUST_BE_SEPARATE", pytrace=False)

    def emit(status, **fields):
        with capsys.disabled():
            print(json.dumps({"status": status, **fields}), flush=True)

    async def verify():
        store = OAuthStore(directory / "oauth.json")
        async with authorized_http(store=store) as http:

            @asynccontextmanager
            async def reuse():
                yield http

            async with NativeMcpClient(reuse).session(("accounts",)):
                pass
            context = http.auth.context
            state = context.storage.state
            access = context.current_tokens.access_token
            assert context.is_token_valid() and state.refresh_token and state.client
            data = {
                "grant_type": "refresh_token",
                "refresh_token": state.refresh_token,
                "client_id": state.client["client_id"],
            }
            if context.should_include_resource_param(context.protocol_version):
                data["resource"] = context.get_resource_url()
        emit("DISPOSABLE_CONNECTION_VALIDATED")
        await revoke_command(store, state.generation)
        emit("REVOCATION_REQUEST_ACCEPTED")
        async with httpx2.AsyncClient(
            transport=BoundedTransport(), timeout=30, trust_env=False, follow_redirects=False
        ) as probe:
            metadata = await public_metadata(probe)
            response = await probe.post(str(metadata.token_endpoint), data=data)
            try:
                payload = response.json()
            except ValueError:
                payload = None
            refresh = refresh_outcome(response.status_code, payload)
        emit("SERVER_REFRESH_PROBE", outcome=refresh)
        statuses = []

        async def observe(response):
            if str(response.request.url) == MCP_URL:
                statuses.append(response.status_code)

        @asynccontextmanager
        async def retained_access():
            async def guard(request):
                if str(request.url) != MCP_URL:
                    raise ValueError("MCP_PROBE_DESTINATION_REJECTED")

            async with httpx2.AsyncClient(
                transport=BoundedTransport(),
                timeout=30,
                trust_env=False,
                follow_redirects=False,
                headers={"Authorization": "Bearer " + access},
                event_hooks={"request": [guard], "response": [observe]},
            ) as probe:
                yield probe

        connected = False
        try:
            async with NativeMcpClient(retained_access).session(("accounts",)):
                connected = True
        except Exception:
            pass
        access_result = access_outcome(connected, statuses)
        emit("SERVER_ACCESS_PROBE", outcome=access_result)
        if refresh != "REJECTED_INVALID_GRANT" or access_result == "INCONCLUSIVE":
            raise ValueError("MCP_SERVER_REVOCATION_NOT_VALIDATED")
        emit(
            "SERVER_REFRESH_REVOCATION_VALIDATED",
            immediate_access_revocation=access_result == "REJECTED_HTTP_401",
        )

    try:
        asyncio.run(verify())
    except Exception:
        pytest.fail("MCP_SERVER_REVOCATION_ACCEPTANCE_FAILED", pytrace=False)
