"""Synthetic handoff assertions shared by the host and the actual bridge image."""

import asyncio
import os
import stat
from pathlib import Path

import httpx2
from mcp_auth_peer import AuthPeer, unattended

from app.mcp_auth import OAuthStore, authorized_http
from app.mcp_client import McpFailure


def assert_private(store):
    directory = store.path.parent.stat()
    assert (directory.st_uid, directory.st_gid) == (os.getuid(), os.getgid())
    assert stat.S_IMODE(directory.st_mode) == 0o700
    for suffix in ("", ".lock", ".lease"):
        info = Path(str(store.path) + suffix).lstat()
        assert stat.S_ISREG(info.st_mode)
        assert stat.S_IMODE(info.st_mode) == 0o600
        assert (info.st_uid, info.st_gid) == (os.getuid(), os.getgid())
    assert "synthetic-access" not in store.path.read_text()


def renew(store):
    before = store.read()
    peer = AuthPeer()
    peer.rotation = int(before.refresh_token.rsplit("-", 1)[1])
    asyncio.run(unattended(store, peer))
    after = store.read()
    assert peer.token_requests == ["refresh_token"]
    assert peer.registrations == 0
    assert after.generation != before.generation
    assert after.refresh_token != before.refresh_token
    assert_private(store)


def reject(store):
    requests = []
    opened = False

    def forbidden(request):
        requests.append(request)
        raise AssertionError("Invalid ownership reached HTTP")

    async def attempt():
        nonlocal opened
        async with authorized_http(store=store, transport=httpx2.MockTransport(forbidden)):
            opened = True

    try:
        asyncio.run(attempt())
    except McpFailure as error:
        assert error.code == "MCP_AUTH_UNAVAILABLE"
    else:
        raise AssertionError("Invalid ownership was accepted")
    assert not requests and not opened


if __name__ == "__main__":
    import pwd
    import sys

    store = OAuthStore(Path(os.environ["FINARY_MCP_STATE_PATH"]))
    if sys.argv[1] == "reject":
        reject(store)
    else:
        try:
            pwd.getpwuid(os.getuid())
        except KeyError:
            pass
        else:
            raise AssertionError("Regression requires a numeric identity without a passwd entry")
        renew(store)
    print("SYNTHETIC_HANDOFF_VALIDATED")
