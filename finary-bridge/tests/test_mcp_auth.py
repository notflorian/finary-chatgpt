"""Pinned SDK OAuth against synthetic HTTP with disposable protected state."""

import asyncio
import json
import os
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx2
import pytest
from mcp.client.auth import AuthorizationCodeResult
from mcp_wire import SyntheticWire

from app.mcp_auth import (
    CALLBACK,
    ISSUER,
    ISSUER_METADATA,
    RESOURCE_METADATA,
    OAuthState,
    OAuthStore,
    RenewableStorage,
    authorized_http,
)
from app.mcp_client import MCP_URL, McpFailure, NativeMcpClient


class AuthPeer(SyntheticWire):
    def __init__(self):
        super().__init__()
        self.token_requests = []
        self.registrations = 0
        self.rotation = 0
        self.reject_refresh = False
        self.expiry = 3600

    def respond(self, request):
        url = str(request.url)
        if url == RESOURCE_METADATA:
            return httpx2.Response(
                200,
                json={
                    "resource": MCP_URL,
                    "authorization_servers": [ISSUER],
                    "scopes_supported": ["openid", "offline_access"],
                },
            )
        if url == ISSUER_METADATA:
            return httpx2.Response(
                200,
                json={
                    "issuer": ISSUER,
                    "authorization_endpoint": ISSUER + "/oauth/authorize",
                    "token_endpoint": ISSUER + "/oauth/token",
                    "registration_endpoint": ISSUER + "/oauth/register",
                    "revocation_endpoint": ISSUER + "/oauth/token/revoke",
                    "response_types_supported": ["code"],
                    "grant_types_supported": ["authorization_code", "refresh_token"],
                    "code_challenge_methods_supported": ["S256"],
                    "token_endpoint_auth_methods_supported": ["none"],
                    "scopes_supported": ["openid", "offline_access"],
                },
            )
        if url == ISSUER + "/oauth/register":
            self.registrations += 1
            return httpx2.Response(
                201, json={**json.loads(request.content), "client_id": "synthetic-local-client"}
            )
        if url == ISSUER + "/oauth/token":
            fields = parse_qs(request.content.decode())
            self.token_requests.append(fields["grant_type"][0])
            if self.reject_refresh and fields["grant_type"] == ["refresh_token"]:
                return httpx2.Response(
                    400, json={"error": "invalid_grant", "error_description": "synthetic-secret"}
                )
            self.rotation += 1
            return httpx2.Response(
                200,
                json={
                    "access_token": "synthetic-access",
                    "token_type": "Bearer",
                    "refresh_token": f"synthetic-renewable-{self.rotation}",
                    "scope": "openid offline_access",
                    "expires_in": self.expiry,
                },
            )
        if url == MCP_URL and request.headers.get("authorization") != "Bearer synthetic-access":
            return httpx2.Response(
                401, headers={"WWW-Authenticate": f'Bearer resource_metadata="{RESOURCE_METADATA}"'}
            )
        return super().respond(request)


async def consent(store, peer):
    result = None

    async def redirect(url):
        nonlocal result
        fields = parse_qs(urlsplit(url).query)
        assert fields["redirect_uri"] == [CALLBACK]
        assert fields["code_challenge_method"] == ["S256"]
        result = AuthorizationCodeResult(
            code="synthetic-code", state=fields["state"][0], iss=ISSUER
        )

    async def callback():
        return result

    def factory():
        return authorized_http(
            store=store,
            bootstrap=True,
            redirect=redirect,
            callback=callback,
            transport=httpx2.MockTransport(peer.respond),
        )

    async with NativeMcpClient(factory).session(("accounts",)) as session:
        await session.call("accounts", {})


async def unattended(store, peer):
    def factory():
        return authorized_http(store=store, transport=httpx2.MockTransport(peer.respond))

    async with NativeMcpClient(factory).session(("accounts",)) as session:
        await session.call("accounts", {})


def test_consent_restart_rotation_and_memory_only_access(tmp_path):
    store = OAuthStore(tmp_path / "oauth/state.json")
    peer = AuthPeer()
    asyncio.run(consent(store, peer))
    first = store.read()
    assert first.refresh_token == "synthetic-renewable-1"
    assert set(first.client) == {
        "client_id",
        "issuer",
        "redirect_uris",
        "token_endpoint_auth_method",
    }
    assert "synthetic-access" not in store.path.read_text()
    assert "synthetic-code" not in store.path.read_text()
    assert os.stat(store.path).st_mode & 0o777 == 0o600
    assert os.stat(store.path.parent).st_mode & 0o777 == 0o700
    asyncio.run(unattended(store, peer))
    assert peer.token_requests == ["authorization_code", "refresh_token"]
    assert peer.registrations == 1
    assert store.read().generation != first.generation


def test_revoked_refresh_never_opens_consent_or_deletes_state(tmp_path, caplog):
    store = OAuthStore(tmp_path / "oauth/state.json")
    peer = AuthPeer()
    asyncio.run(consent(store, peer))
    state = store.read()
    peer.reject_refresh = True
    with pytest.raises(McpFailure):
        asyncio.run(unattended(store, peer))
    assert store.read().generation == state.generation
    assert peer.registrations == 1
    assert "synthetic-secret" not in caplog.text


def test_expiry_and_concurrent_cold_restarts_are_serialized(tmp_path):
    store = OAuthStore(tmp_path / "oauth/state.json")
    peer = AuthPeer()
    asyncio.run(consent(store, peer))

    async def concurrent():
        await asyncio.gather(unattended(store, peer), unattended(store, peer))

    asyncio.run(concurrent())
    assert peer.token_requests.count("refresh_token") == 2
    assert store.read().refresh_token == "synthetic-renewable-3"


def test_operator_replacement_wins_against_old_refresh(tmp_path):
    store = OAuthStore(tmp_path / "oauth/state.json")
    peer = AuthPeer()
    asyncio.run(consent(store, peer))
    older = RenewableStorage(store)
    before = store.read()
    replacement = store.replace(
        before.generation, OAuthState("", before.client, "synthetic-replacement", before.scope)
    )
    from mcp.shared.auth import OAuthToken

    with pytest.raises(McpFailure):
        asyncio.run(
            older.set_tokens(
                OAuthToken(
                    access_token="synthetic-memory",
                    token_type="Bearer",
                    refresh_token="synthetic-stale",
                )
            )
        )
    assert store.read().generation == replacement.generation


@pytest.mark.parametrize("mode", ["directory", "file", "symlink", "malformed"])
def test_private_store_rejects_unsafe_state(tmp_path, mode):
    store = OAuthStore(tmp_path / "oauth/state.json")
    store.replace("", OAuthState(""))
    if mode == "directory":
        store.path.parent.chmod(0o755)
    if mode == "file":
        store.path.chmod(0o644)
    if mode == "symlink":
        destination = Path(str(store.path) + ".saved")
        store.path.rename(destination)
        store.path.symlink_to(destination)
    if mode == "malformed":
        store.path.write_text('{"unexpected":"synthetic"}')
    with pytest.raises((McpFailure, OSError)):
        store.read()


def test_expired_memory_token_renews_without_consent(tmp_path):
    store = OAuthStore(tmp_path / "oauth/state.json")
    peer = AuthPeer()
    asyncio.run(consent(store, peer))

    async def expire():
        async with authorized_http(
            store=store, transport=httpx2.MockTransport(peer.respond)
        ) as http:
            await http.post(MCP_URL, json={"jsonrpc": "2.0", "id": 1, "method": "initialize"})
            http.auth.context.token_expiry_time = 1
            await http.post(MCP_URL, json={"jsonrpc": "2.0", "id": 2, "method": "initialize"})

    asyncio.run(expire())
    assert peer.token_requests == ["authorization_code", "refresh_token", "refresh_token"]
    assert peer.registrations == 1


def test_explicit_revoke_tombstone_and_generation_guard(tmp_path, capsys):
    from app.mcp_auth import revoke_command

    store = OAuthStore(tmp_path / "oauth/state.json")
    peer = AuthPeer()
    asyncio.run(consent(store, peer))
    state = store.read()
    calls = []

    def respond(request):
        if str(request.url) == ISSUER + "/oauth/token/revoke":
            calls.append(parse_qs(request.content.decode()))
            return httpx2.Response(200)
        return peer.respond(request)

    with pytest.raises(McpFailure):
        asyncio.run(
            revoke_command(store, "not-this-generation", transport=httpx2.MockTransport(respond))
        )
    assert not calls
    asyncio.run(revoke_command(store, state.generation, transport=httpx2.MockTransport(respond)))
    assert len(calls) == 1 and calls[0]["token_type_hint"] == ["refresh_token"]
    assert store.read().refresh_token is None
    assert store.read().generation != state.generation
    assert "synthetic-renewable" not in capsys.readouterr().out
