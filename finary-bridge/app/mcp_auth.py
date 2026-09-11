"""Independent OAuth lifecycle using the pinned SDK and a protected renewable store."""

from __future__ import annotations

import argparse
import asyncio
import fcntl
import json
import os
import stat
import tempfile
import webbrowser
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import httpx2
from mcp.client.auth import AuthorizationCodeResult, OAuthClientProvider
from mcp.shared.auth import (
    OAuthClientInformationFull,
    OAuthClientMetadata,
    OAuthMetadata,
    OAuthToken,
)
from pydantic import AnyUrl

from app.mcp_client import MCP_URL, BoundedTransport, McpFailure, suppress_sdk_diagnostics

ISSUER = "https://clerk.finary.com"
RESOURCE_METADATA = "https://public-api.finary.com/.well-known/oauth-protected-resource/mcp"
ISSUER_METADATA = ISSUER + "/.well-known/oauth-authorization-server"
CALLBACK = "http://127.0.0.1:8765/callback"


def private_stat(info: os.stat_result, mode: int) -> None:
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != mode:
        raise McpFailure("MCP_AUTH_UNAVAILABLE")


@dataclass(repr=False)
class OAuthState:
    generation: str
    client: dict[str, Any] | None = field(default=None, repr=False)
    refresh_token: str | None = field(default=None, repr=False)
    scope: str | None = None


class OAuthStore:
    """CAS rotation and a separate session lease protect concurrent processes."""

    def __init__(self, path: Path) -> None:
        if not path.is_absolute():
            raise McpFailure("MCP_AUTH_UNAVAILABLE")
        self.path = path

    def directory(self) -> None:
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = self.path.parent.lstat()
        if not stat.S_ISDIR(info.st_mode):
            raise McpFailure("MCP_AUTH_UNAVAILABLE")
        private_stat(info, 0o700)

    @contextmanager
    def locked(self) -> Iterator[None]:
        self.directory()
        fd = os.open(str(self.path) + ".lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            private_stat(os.fstat(fd), 0o600)
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield
        except (OSError, ValueError):
            raise McpFailure("MCP_AUTH_UNAVAILABLE") from None
        finally:
            os.close(fd)

    def _read(self) -> OAuthState:
        try:
            fd = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except FileNotFoundError:
            return OAuthState("")
        with os.fdopen(fd) as handle:
            info = os.fstat(handle.fileno())
            private_stat(info, 0o600)
            if not stat.S_ISREG(info.st_mode) or info.st_size > 32768:
                raise McpFailure("MCP_AUTH_UNAVAILABLE")
            try:
                value = json.load(handle)
                if (
                    set(value) != {"format", "generation", "client", "refresh_token", "scope"}
                    or value["format"] != 1
                ):
                    raise ValueError
                from uuid import UUID

                UUID(value["generation"])
                if value["client"] is not None:
                    client = OAuthClientInformationFull.model_validate(value["client"])
                    if client.issuer != ISSUER:
                        raise ValueError
                refresh = value["refresh_token"]
                if refresh is not None and (
                    not isinstance(refresh, str) or not 0 < len(refresh) <= 16384
                ):
                    raise ValueError
                scope = value["scope"]
                if scope is not None and (not isinstance(scope, str) or len(scope) > 512):
                    raise ValueError
                return OAuthState(value["generation"], value["client"], refresh, scope)
            except (TypeError, ValueError, KeyError):
                raise McpFailure("MCP_AUTH_UNAVAILABLE") from None

    def read(self) -> OAuthState:
        with self.locked():
            return self._read()

    def replace(self, expected: str, state: OAuthState) -> OAuthState:
        with self.locked():
            if self._read().generation != expected:
                raise McpFailure("MCP_AUTH_UNAVAILABLE")
            generation = str(uuid4())
            value = {
                "format": 1,
                "generation": generation,
                "client": state.client,
                "refresh_token": state.refresh_token,
                "scope": state.scope,
            }
            fd, filename = tempfile.mkstemp(prefix=".oauth-", dir=self.path.parent)
            try:
                with os.fdopen(fd, "w") as handle:
                    os.fchmod(handle.fileno(), 0o600)
                    json.dump(value, handle)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(filename, self.path)
                directory_fd = os.open(self.path.parent, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            finally:
                if os.path.exists(filename):
                    os.unlink(filename)
            return OAuthState(generation, state.client, state.refresh_token, state.scope)

    @asynccontextmanager
    async def lease(self) -> AsyncIterator[None]:
        self.directory()
        fd = os.open(str(self.path) + ".lease", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            private_stat(os.fstat(fd), 0o600)
            for _ in range(200):
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    await asyncio.sleep(0.05)
            else:
                raise McpFailure("MCP_AUTH_UNAVAILABLE")
            yield
        finally:
            os.close(fd)


class RenewableStorage:
    """SDK storage: access tokens live only in this session; restart uses refresh."""

    def __init__(self, store: OAuthStore, *, bootstrap: bool = False) -> None:
        self.store = store
        self.state = store.read()
        self.bootstrap = bootstrap
        self.tokens: OAuthToken | None = None

    async def get_tokens(self) -> OAuthToken | None:
        if self.tokens is not None:
            return self.tokens
        if self.state.refresh_token:
            return OAuthToken(
                access_token="",
                token_type="Bearer",
                expires_in=0,
                refresh_token=self.state.refresh_token,
                scope=self.state.scope,
            )
        return None

    async def set_tokens(self, tokens: OAuthToken) -> None:
        if not tokens.refresh_token:
            raise McpFailure("MCP_AUTH_UNAVAILABLE")
        self.state = self.store.replace(
            self.state.generation,
            OAuthState("", self.state.client, tokens.refresh_token, tokens.scope),
        )
        self.tokens = tokens

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        return (
            OAuthClientInformationFull.model_validate(self.state.client)
            if self.state.client
            else None
        )

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        if not self.bootstrap or client_info.issuer != ISSUER:
            raise McpFailure("MCP_AUTH_UNAVAILABLE")
        self.state = self.store.replace(
            self.state.generation,
            OAuthState("", client_info.model_dump(mode="json", exclude_none=True), None, None),
        )


async def public_metadata(http: httpx2.AsyncClient) -> OAuthMetadata:
    resource_response = await http.get(RESOURCE_METADATA)
    issuer_response = await http.get(ISSUER_METADATA)
    resource_response.raise_for_status()
    issuer_response.raise_for_status()
    resource = resource_response.json()
    metadata = OAuthMetadata.model_validate(issuer_response.json())
    if (
        resource.get("resource") != MCP_URL
        or resource.get("authorization_servers") != [ISSUER]
        or str(metadata.issuer) != ISSUER
    ):
        raise McpFailure("MCP_AUTH_UNAVAILABLE")
    for endpoint in (
        metadata.authorization_endpoint,
        metadata.token_endpoint,
        metadata.registration_endpoint,
    ):
        if endpoint is not None:
            url = urlsplit(str(endpoint))
            if url.scheme != "https" or url.netloc != "clerk.finary.com" or url.username:
                raise McpFailure("MCP_AUTH_UNAVAILABLE")
    return metadata


async def deny_redirect(url: str) -> None:
    del url
    raise McpFailure("MCP_AUTH_UNAVAILABLE")


async def deny_callback() -> AuthorizationCodeResult:
    raise McpFailure("MCP_AUTH_UNAVAILABLE")


@asynccontextmanager
async def authorized_http(
    *,
    store: OAuthStore | None = None,
    bootstrap: bool = False,
    redirect: Any = deny_redirect,
    callback: Any = deny_callback,
    transport: httpx2.AsyncBaseTransport | None = None,
) -> AsyncIterator[httpx2.AsyncClient]:
    suppress_sdk_diagnostics()
    if store is None:
        path = os.getenv("FINARY_MCP_STATE_PATH")
        if not path:
            raise McpFailure("MCP_AUTH_UNAVAILABLE")
        store = OAuthStore(Path(path))
    try:
        async with store.lease():
            storage = RenewableStorage(store, bootstrap=bootstrap)
            if not bootstrap and (not storage.state.refresh_token or not storage.state.client):
                raise McpFailure("MCP_AUTH_UNAVAILABLE")
            async with httpx2.AsyncClient(
                transport=BoundedTransport(transport),
                timeout=30,
                trust_env=False,
                follow_redirects=False,
            ) as http:
                metadata = await public_metadata(http)
                if not metadata.token_endpoint:
                    raise McpFailure("MCP_AUTH_UNAVAILABLE")

                async def guard(request: httpx2.Request) -> None:
                    url = str(request.url)
                    allowed = {
                        MCP_URL,
                        RESOURCE_METADATA,
                        ISSUER_METADATA,
                        str(metadata.token_endpoint),
                    }
                    if bootstrap and metadata.registration_endpoint:
                        allowed.add(str(metadata.registration_endpoint))
                    if url not in allowed:
                        raise McpFailure("MCP_AUTH_UNAVAILABLE")

                http.event_hooks["request"] = [guard]
                auth = OAuthClientProvider(
                    MCP_URL,
                    OAuthClientMetadata(
                        client_name="Finary local bridge",
                        redirect_uris=[AnyUrl(CALLBACK)],
                        token_endpoint_auth_method="none",
                    ),
                    storage,
                    redirect_handler=redirect,
                    callback_handler=callback,
                )
                # The pinned SDK exposes AuthContext. Seed freshly validated metadata
                # before cold-start refresh to avoid its legacy /token fallback.
                auth.context.oauth_metadata = metadata
                auth.context.auth_server_url = ISSUER
                http.auth = auth
                yield http
    except McpFailure:
        raise
    except Exception:
        raise McpFailure("MCP_AUTH_UNAVAILABLE") from None


async def bootstrap_command(store: OAuthStore) -> None:
    loop = asyncio.get_running_loop()
    callback_result: asyncio.Future[AuthorizationCodeResult] = loop.create_future()

    async def receive(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            line = await asyncio.wait_for(reader.readline(), timeout=5)
            method, target, _ = line.decode("ascii").split()
            parsed = urlsplit(target)
            if method != "GET" or parsed.path != "/callback" or len(line) > 8192:
                raise ValueError
            values = parse_qs(parsed.query, strict_parsing=True)
            if any(len(v) != 1 for v in values.values()):
                raise ValueError
            result = AuthorizationCodeResult(
                code=values["code"][0], state=values["state"][0], iss=values.get("iss", [None])[0]
            )
            if not callback_result.done():
                callback_result.set_result(result)
            writer.write(
                b"HTTP/1.1 200 OK\r\nConnection: close\r\nContent-Type: text/plain\r\n\r\n"
                b"Return to the operator command.\n"
            )
            await writer.drain()
        except Exception:
            pass
        finally:
            writer.close()

    async def redirect(url: str) -> None:
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.netloc != "clerk.finary.com":
            raise McpFailure("MCP_AUTH_UNAVAILABLE")
        if not webbrowser.open(url):
            raise McpFailure("MCP_AUTH_UNAVAILABLE")

    async def callback() -> AuthorizationCodeResult:
        return await asyncio.wait_for(callback_result, timeout=120)

    from app.mcp_client import NativeMcpClient

    server = await asyncio.start_server(receive, "127.0.0.1", 8765, limit=8192)
    async with server:
        client = NativeMcpClient(
            lambda: authorized_http(
                store=store, bootstrap=True, redirect=redirect, callback=callback
            )
        )
        async with client.session(("accounts", "holdings", "get_portfolio_overview")) as session:
            print(
                json.dumps(
                    {
                        "status": "AUTHORIZED",
                        "protocol_revision": session.client.protocol_version,
                        "required_tools": True,
                    }
                )
            )


async def revoke_command(store: OAuthStore, expected_generation: str) -> None:
    """Only an explicit operator invocation revokes this store's connection."""
    async with store.lease():
        state = store.read()
        if state.generation != expected_generation or not state.refresh_token or not state.client:
            raise McpFailure("MCP_AUTH_UNAVAILABLE")
        async with httpx2.AsyncClient(
            transport=BoundedTransport(), timeout=30, trust_env=False
        ) as http:
            metadata = await public_metadata(http)
            endpoint = getattr(metadata, "revocation_endpoint", None)
            if endpoint is None or urlsplit(str(endpoint)).netloc != "clerk.finary.com":
                raise McpFailure("MCP_AUTH_UNAVAILABLE")
            client = OAuthClientInformationFull.model_validate(state.client)
            if client.token_endpoint_auth_method != "none":
                raise McpFailure("MCP_AUTH_UNAVAILABLE")
            response = await http.post(
                str(endpoint),
                data={
                    "token": state.refresh_token,
                    "token_type_hint": "refresh_token",
                    "client_id": client.client_id,
                },
            )
            response.raise_for_status()
            store.replace(state.generation, OAuthState(""))
            print('{"status":"REVOCATION_REQUEST_ACCEPTED"}')


def main() -> None:
    parser = argparse.ArgumentParser(description="Independent Finary MCP operator authorization")
    parser.add_argument("command", choices=("bootstrap", "status", "revoke"))
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--expected-generation")
    args = parser.parse_args()
    suppress_sdk_diagnostics()
    try:
        store = OAuthStore(args.state)
        if args.command == "status":
            state = store.read()
            print(
                json.dumps(
                    {
                        "status": "RENEWABLE_STATE_PRESENT"
                        if state.refresh_token
                        else "MCP_AUTH_UNAVAILABLE",
                        "generation": state.generation,
                        "live_validity": "UNVERIFIED",
                    }
                )
            )
        elif args.command == "bootstrap":
            asyncio.run(bootstrap_command(store))
        elif args.expected_generation:
            asyncio.run(revoke_command(store, args.expected_generation))
        else:
            raise McpFailure("MCP_INVALID_ARGUMENT")
    except Exception:
        print(
            '{"status":"MCP_AUTH_UNAVAILABLE",'
            '"action":"Review the independent OAuth operator runbook"}'
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
