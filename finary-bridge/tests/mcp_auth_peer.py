"""Synthetic OAuth consent and renewable sessions over fake HTTP only."""

import json
from urllib.parse import parse_qs, urlsplit

import httpx2
from mcp.client.auth import AuthorizationCodeResult
from mcp_wire import SyntheticWire

from app.mcp_auth import CALLBACK, ISSUER, ISSUER_METADATA, RESOURCE_METADATA, authorized_http
from app.mcp_client import MCP_URL, NativeMcpClient


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
