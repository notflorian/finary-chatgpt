"""Pinned SDK OAuth against synthetic HTTP with disposable protected state."""

import asyncio
import json
import multiprocessing
import os
from contextlib import contextmanager
from pathlib import Path
from time import monotonic
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
        self.resource_scopes = ["openid", "offline_access"]
        self.server_scopes = ["openid", "offline_access"]
        self.challenge_scope = None
        self.response_scope = "openid offline_access"
        self.authorization_fields = []
        self.token_fields = []

    def respond(self, request):
        url = str(request.url)
        if url == RESOURCE_METADATA:
            return httpx2.Response(
                200,
                json={
                    "resource": MCP_URL,
                    "authorization_servers": [ISSUER],
                    "scopes_supported": self.resource_scopes,
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
                    "scopes_supported": self.server_scopes,
                },
            )
        if url == ISSUER + "/oauth/register":
            self.registrations += 1
            return httpx2.Response(
                201, json={**json.loads(request.content), "client_id": "synthetic-local-client"}
            )
        if url == ISSUER + "/oauth/token":
            fields = parse_qs(request.content.decode())
            self.token_fields.append(fields)
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
                    **({"scope": self.response_scope} if self.response_scope is not None else {}),
                    "expires_in": self.expiry,
                },
            )
        if url == MCP_URL and request.headers.get("authorization") != "Bearer synthetic-access":
            challenge = f'Bearer resource_metadata="{RESOURCE_METADATA}"'
            if self.challenge_scope is not None:
                challenge += f', scope="{self.challenge_scope}"'
            return httpx2.Response(
                401, headers={"WWW-Authenticate": challenge}
            )
        return super().respond(request)


async def consent(store, peer, diagnostics=None):
    result = None

    async def redirect(url):
        nonlocal result
        fields = parse_qs(urlsplit(url).query)
        peer.authorization_fields.append(fields)
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


@pytest.mark.parametrize(
    "challenge,resource,server,expected",
    [
        ("email", ["profile"], ["openid", "offline_access"], "email offline_access"),
        (None, ["openid", "profile", "email"], ["offline_access"],
         "openid profile email offline_access"),
        (None, None, ["profile", "offline_access"], "profile offline_access"),
        (None, None, None, None),
        ("email", ["profile"], ["openid"], "email"),
        ("email offline_access", ["profile"], ["offline_access"], "email offline_access"),
        ("EMAIL OFFLINE_ACCESS", ["email"], ["offline_access"],
         "EMAIL OFFLINE_ACCESS offline_access"),
        ("email offline_access_extra", ["email"], ["offline_access"],
         "email offline_access_extra offline_access"),
        ("email", ["profile"], ["OFFLINE_ACCESS"], "email"),
    ],
)
def test_sdk_effective_authorization_scopes_replace_constructor(
    tmp_path, challenge, resource, server, expected
):
    store = OAuthStore(tmp_path / "oauth/state.json")
    peer = AuthPeer()
    peer.challenge_scope = challenge
    peer.resource_scopes = resource
    peer.server_scopes = server
    peer.response_scope = None
    asyncio.run(consent(store, peer))
    fields = peer.authorization_fields[0]
    assert fields.get("scope") == ([expected] if expected else None)
    assert fields.get("prompt") == (
        ["consent"] if expected and "offline_access" in expected.split(" ") else None
    )
    assert store.read().scope == expected
    assert "scope" not in peer.token_fields[0]


@pytest.mark.parametrize(
    "initial", [None, "profile offline_access", "EMAIL profile offline_access"]
)
@pytest.mark.parametrize("refreshed", [None, "profile", "offline_access"])
def test_sdk_explicit_and_omitted_scope_evidence_survives_restart(tmp_path, initial, refreshed):
    store = OAuthStore(tmp_path / "oauth/state.json")
    peer = AuthPeer()
    peer.challenge_scope = "email profile"
    peer.response_scope = initial
    asyncio.run(consent(store, peer))
    effective = "email profile offline_access" if initial is None else initial
    assert store.read().scope == effective
    peer.response_scope = refreshed
    asyncio.run(unattended(store, peer))
    assert store.read().scope == (effective if refreshed is None else refreshed)
    assert "scope" not in peer.token_fields[-1]
    assert peer.registrations == 1 and len(peer.authorization_fields) == 1


def test_refresh_cannot_recover_unknown_stored_scope_provenance(tmp_path):
    store = OAuthStore(tmp_path / "oauth/state.json")
    peer = AuthPeer()
    asyncio.run(consent(store, peer))
    state = store.read()
    store.replace(state.generation, OAuthState("", state.client, state.refresh_token, None))
    peer.response_scope = None
    asyncio.run(unattended(store, peer))
    assert store.read().scope is None
    assert len(peer.authorization_fields) == 1


@pytest.mark.parametrize("scope", ["email", "EMAIL offline_access_extra", "synthetic-private"])
def test_insufficient_scope_fails_without_unattended_consent(tmp_path, caplog, scope):
    store = OAuthStore(tmp_path / "oauth/state.json")
    peer = AuthPeer()
    asyncio.run(consent(store, peer))
    calls = []

    def respond(request):
        calls.append(str(request.url))
        if str(request.url) == MCP_URL:
            return httpx2.Response(
                403,
                headers={"WWW-Authenticate": f'Bearer error="insufficient_scope", scope="{scope}"'},
                text="synthetic-private-response",
            )
        return peer.respond(request)

    async def rejected():
        async with authorized_http(store=store, transport=httpx2.MockTransport(respond)) as http:
            await http.post(MCP_URL, json={"jsonrpc": "2.0", "id": 1, "method": "initialize"})

    with pytest.raises(McpFailure) as rejected_scope:
        asyncio.run(rejected())
    assert rejected_scope.value.code == "MCP_AUTH_UNAVAILABLE"
    assert calls.count(MCP_URL) == 1
    assert peer.registrations == 1 and len(peer.authorization_fields) == 1
    assert store.read().refresh_token == "synthetic-renewable-2"
    assert "synthetic-private" not in caplog.text


def test_missing_authorization_fails_before_http_or_registration(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Missing authorization reached HTTP construction")

    monkeypatch.setattr(httpx2, "AsyncClient", forbidden)
    store = OAuthStore(tmp_path / "oauth/state.json")
    with pytest.raises(McpFailure) as unavailable:
        asyncio.run(unattended(store, AuthPeer()))
    assert unavailable.value.code == "MCP_AUTH_UNAVAILABLE"
    assert not store.path.exists()


@pytest.mark.parametrize("scope", [None, "openid email", "EMAIL", "synthetic-private", ["secret"]])
def test_local_status_keeps_scope_unknown_and_never_uses_network(
    tmp_path, monkeypatch, capsys, scope
):
    import app.mcp_auth as auth

    store = OAuthStore(tmp_path / "oauth/state.json")
    asyncio.run(consent(store, AuthPeer()))
    payload = json.loads(store.path.read_text())
    payload["scope"] = scope
    store.path.write_text(json.dumps(payload))
    before = store.path.read_bytes(), store.path.stat()

    def forbidden(*args, **kwargs):
        pytest.fail("Local status attempted network, consent or state replacement")

    monkeypatch.setattr(httpx2, "AsyncClient", forbidden)
    monkeypatch.setattr(auth, "bootstrap_command", forbidden)
    monkeypatch.setattr(auth, "revoke_command", forbidden)
    monkeypatch.setattr(OAuthStore, "replace", forbidden)
    monkeypatch.setattr("sys.argv", ["mcp_auth", "status", "--state", str(store.path)])
    if isinstance(scope, list):
        with pytest.raises(SystemExit) as stopped:
            auth.main()
        assert stopped.value.code == 1
        assert json.loads(capsys.readouterr().out) == {
            "status": "MCP_AUTH_UNAVAILABLE",
            "action": "Review the independent OAuth operator runbook",
        }
    else:
        auth.main()
        assert json.loads(capsys.readouterr().out) == {
            "status": "RENEWABLE_STATE_PRESENT",
            "generation": payload["generation"],
            "live_validity": "UNVERIFIED",
        }
    after = store.path.stat()
    assert store.path.read_bytes() == before[0]
    assert (after.st_ino, after.st_mtime_ns, after.st_mode) == (
        before[1].st_ino, before[1].st_mtime_ns, before[1].st_mode
    )


@pytest.mark.parametrize("response_scope", ["synthetic-private-scope", ["synthetic-private-scope"]])
def test_scope_values_never_enter_bootstrap_diagnostics(tmp_path, capsys, caplog, response_scope):
    from app.mcp_auth import BootstrapDiagnostics

    peer = AuthPeer()
    peer.response_scope = response_scope
    store = OAuthStore(tmp_path / "oauth/state.json")
    if isinstance(response_scope, list):
        with pytest.raises(McpFailure):
            asyncio.run(consent(store, peer, BootstrapDiagnostics()))
        assert store.read().refresh_token is None
    else:
        asyncio.run(consent(store, peer, BootstrapDiagnostics()))
    output = capsys.readouterr().out
    assert all(
        set(json.loads(line)["diagnostic"]) <= {"stage", "http_status"}
        for line in output.splitlines()
    )
    assert "synthetic-private" not in output + caplog.text


def oauth_process(path, channel, mode, expected_refresh):
    """Spawned interpreter uses real OAuth/storage with only HTTP replaced."""
    peer = AuthPeer()
    peer.reject_refresh = mode == "reject_refresh"
    requests = 0

    async def pause(stage):
        channel.send(stage)
        if not await asyncio.to_thread(channel.poll, 25):
            raise RuntimeError("Synthetic process coordination timed out")
        assert channel.recv() == "CONTINUE"

    async def respond(request):
        nonlocal requests
        requests += 1
        if str(request.url) == ISSUER + "/oauth/token":
            fields = parse_qs(request.content.decode())
            assert fields["refresh_token"] == [expected_refresh]
            peer.rotation = int(expected_refresh.rsplit("-", 1)[1])
            if mode in {"pause_refresh", "reject_refresh"}:
                await pause("REFRESH_PENDING")
        return peer.respond(request)

    async def run():
        def factory():
            return authorized_http(
                store=OAuthStore(Path(path)), transport=httpx2.MockTransport(respond)
            )

        async with NativeMcpClient(factory).session(("accounts",)) as session:
            await session.call("accounts", {})
            if mode == "hold_session":
                await pause("SESSION_OPEN")

    start = monotonic()
    try:
        asyncio.run(run())
        outcome = "SUCCESS"
    except McpFailure as error:
        outcome = error.code
    channel.send((outcome, requests, monotonic() - start))
    channel.close()


@contextmanager
def independent_oauth(store, mode="normal", expected_refresh="synthetic-renewable-1"):
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe()
    process = context.Process(
        target=oauth_process, args=(str(store.path), child, mode, expected_refresh)
    )
    process.start()
    child.close()
    try:
        yield parent
        process.join(timeout=5)
        assert process.exitcode == 0
    finally:
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)
        parent.close()
        process.close()


def receive_process(channel):
    assert channel.poll(20), "Synthetic OAuth process exceeded its wait bound"
    return channel.recv()


def test_process_lease_covers_session_and_contention_is_bounded(tmp_path):
    store = OAuthStore(tmp_path / "oauth/state.json")
    asyncio.run(consent(store, AuthPeer()))
    with independent_oauth(store, "hold_session") as owner:
        assert receive_process(owner) == "SESSION_OPEN"
        state = store.path.read_bytes()
        with independent_oauth(store) as contender:
            outcome, requests, elapsed = receive_process(contender)
            assert outcome == "MCP_AUTH_UNAVAILABLE"
            assert requests == 0 and 9 <= elapsed < 20
        assert store.path.read_bytes() == state
        owner.send("CONTINUE")
        assert receive_process(owner)[0] == "SUCCESS"
    with independent_oauth(store, expected_refresh="synthetic-renewable-2") as successor:
        assert receive_process(successor)[0] == "SUCCESS"
    assert store.read().refresh_token == "synthetic-renewable-3"


@pytest.mark.parametrize("replacement", [False, True])
@pytest.mark.parametrize("mode", ["pause_refresh", "reject_refresh"])
def test_process_refresh_releases_lease_and_preserves_newer_state(tmp_path, replacement, mode):
    store = OAuthStore(tmp_path / "oauth/state.json")
    asyncio.run(consent(store, AuthPeer()))
    with independent_oauth(store, mode) as owner:
        assert receive_process(owner) == "REFRESH_PENDING"
        before = store.read()
        if replacement:
            store.replace(
                before.generation,
                OAuthState("", before.client, "synthetic-renewable-10", before.scope),
            )
        protected = store.path.read_bytes()
        owner.send("CONTINUE")
        outcome, _, _ = receive_process(owner)
        failed = replacement or mode == "reject_refresh"
        assert outcome == ("MCP_AUTH_UNAVAILABLE" if failed else "SUCCESS")
        if failed:
            assert store.path.read_bytes() == protected
    expected = "synthetic-renewable-10" if replacement else (
        "synthetic-renewable-1" if failed else "synthetic-renewable-2"
    )
    with independent_oauth(store, expected_refresh=expected) as successor:
        assert receive_process(successor)[0] == "SUCCESS"
    assert store.read().generation != before.generation
