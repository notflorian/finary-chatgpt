"""Deterministic observations collected through the real native MCP service."""

import asyncio
from datetime import datetime

from mcp_wire import SyntheticWire

from app.services.mcp_snapshot_service import McpSnapshotService

NOW = datetime.fromisoformat("2026-09-11T10:00:00+02:00")

def snapshot(wire=None, **kwargs):
    return asyncio.run(
        McpSnapshotService(
            (wire or SyntheticWire()).client(), clock=lambda: NOW, **kwargs
        ).snapshot()
    ).model_dump()
