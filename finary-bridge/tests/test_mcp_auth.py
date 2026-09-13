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


async def consent(store, peer, diagnostics=None):
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
            diagnostics=diagnostics,
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


def test_bootstrap_diagnostics_report_only_fixed_stages_and_statuses(tmp_path, capsys):
    from app.mcp_auth import BootstrapDiagnostics

    store = OAuthStore(tmp_path / "oauth/state.json")
    asyncio.run(consent(store, AuthPeer(), BootstrapDiagnostics()))
    output = capsys.readouterr().out
    events = [json.loads(line)["diagnostic"] for line in output.splitlines()]
    assert {event["stage"] for event in events} >= {
        "LOCAL_STATE",
        "RESOURCE_METADATA",
        "ISSUER_METADATA",
        "METADATA_VALIDATION",
        "MCP_INITIALIZATION",
        "CLIENT_REGISTRATION",
        "TOKEN_EXCHANGE",
        "TOOL_DISCOVERY",
    }
    assert any(event == {"stage": "CLIENT_REGISTRATION", "http_status": 201} for event in events)
    assert all(set(event) <= {"stage", "http_status"} for event in events)
    for private in ("synthetic-", "http://", "https://", "state.json", "Bearer"):
        assert private not in output


@pytest.mark.parametrize("diagnose", [False, True])
def test_operator_failure_retains_safe_code_without_exception_text(
    tmp_path, monkeypatch, capsys, diagnose
):
    import app.mcp_auth as auth

    async def fail(store, diagnostics):
        if diagnostics is not None:
            diagnostics.emit("TOOL_DISCOVERY")
        try:
            raise ValueError("synthetic-secret-upstream-response")
        except ValueError:
            raise McpFailure("MCP_CAPABILITY_UNAVAILABLE") from None

    arguments = ["mcp_auth", "bootstrap", "--state", str(tmp_path / "oauth/state.json")]
    if diagnose:
        arguments.append("--diagnose")
    monkeypatch.setattr("sys.argv", arguments)
    monkeypatch.setattr(auth, "bootstrap_command", fail)
    with pytest.raises(SystemExit) as stopped:
        auth.main()
    assert stopped.value.code == 1
    output = capsys.readouterr().out
    outcome = json.loads(output.splitlines()[-1])
    assert outcome["status"] == "MCP_CAPABILITY_UNAVAILABLE"
    if diagnose:
        assert outcome["stage"] == "TOOL_DISCOVERY"
    else:
        assert "stage" not in outcome
    assert "synthetic-secret" not in output


def test_diagnostic_failure_never_prints_registration_error_body(tmp_path, capsys):
    from app.mcp_auth import BootstrapDiagnostics

    class RejectedRegistration(AuthPeer):
        def respond(self, request):
            if str(request.url) == ISSUER + "/oauth/register":
                return httpx2.Response(
                    400,
                    json={
                        "error": "invalid_client_metadata",
                        "error_description": "synthetic-secret-registration-response",
                    },
                )
            return super().respond(request)

    store = OAuthStore(tmp_path / "oauth/state.json")
    diagnostics = BootstrapDiagnostics()
    with pytest.raises(McpFailure):
        asyncio.run(consent(store, RejectedRegistration(), diagnostics))
    output = capsys.readouterr().out
    assert json.loads(output.splitlines()[-1])["diagnostic"] == {
        "stage": "CLIENT_REGISTRATION",
        "http_status": 400,
    }
    assert "synthetic-secret" not in output
    assert store.read().generation == ""


def test_sdk_oauth_requests_supply_http_client_identification(tmp_path):
    class IdentificationRequired(AuthPeer):
        def __init__(self):
            super().__init__()
            self.identification = []

        def respond(self, request):
            agent = request.headers.get("user-agent")
            if not agent:
                return httpx2.Response(403, text="Synthetic unidentified HTTP client")
            self.identification.append(agent)
            return super().respond(request)

    store = OAuthStore(tmp_path / "oauth/state.json")
    peer = IdentificationRequired()
    asyncio.run(consent(store, peer))
    asyncio.run(unattended(store, peer))
    assert peer.token_requests == ["authorization_code", "refresh_token"]
    assert "finary-bridge/1.1.0" in peer.identification
    assert any(agent.startswith("python-httpx") for agent in peer.identification)


@pytest.mark.parametrize("format_value", [True, 1.0, False, "1", None, 2])
def test_store_rejects_wrong_format_type_without_modifying_file(tmp_path, format_value):
    store = OAuthStore(tmp_path / "oauth/state.json")
    store.replace("", OAuthState(""))
    payload = json.loads(store.path.read_text())
    payload["format"] = format_value
    original = json.dumps(payload).encode()
    store.path.write_bytes(original)
    before = store.path.stat()
    with pytest.raises(McpFailure):
        store.read()
    assert store.path.read_bytes() == original
    after = store.path.stat()
    assert (after.st_ino, after.st_mtime_ns, after.st_mode) == (
        before.st_ino,
        before.st_mtime_ns,
        before.st_mode,
    )
