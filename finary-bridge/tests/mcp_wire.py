"""Synthetic HTTP peer for the real pinned MCP SDK; no production replacement logic."""

import json
from contextlib import asynccontextmanager
from copy import deepcopy
from pathlib import Path

import httpx2

from app.mcp_client import BoundedTransport, NativeMcpClient
from app.mcp_validation import CONTRACT

BASES = json.loads((Path(__file__).parent / "fixtures/finary-mcp/bases.json").read_text())


class SyntheticWire:
    def __init__(self):
        self.values = deepcopy(BASES)
        self.calls = []
        self.requests = []
        self.mutate = None
        self.tool_error = None
        self.http_status = None
        self.catalog_pages = None
        self.tools = [
            "get_portfolio_overview",
            "accounts",
            "holdings",
            "get_budget_overview",
            "search_spending",
            "goals",
        ]

    def catalog(self):
        result = []
        for name in self.tools:
            reference = CONTRACT["capabilities"][name]["input_schema"].split("/")[-1]
            schema = deepcopy(CONTRACT["$defs"][reference])
            schema["$defs"] = CONTRACT["$defs"]
            result.append({"name": name, "inputSchema": schema})
        return result

    def respond(self, request):
        if request.method != "POST":
            return httpx2.Response(405)
        message = json.loads(request.content)
        method = message["method"]
        self.requests.append(method)
        if method.startswith("notifications/"):
            return httpx2.Response(202)
        reply = {"jsonrpc": "2.0", "id": message["id"]}
        if method == "server/discover":
            reply["error"] = {"code": -32601, "message": "Synthetic classic peer"}
        elif method == "initialize":
            reply["result"] = {
                "protocolVersion": "2025-11-25",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "Synthetic", "version": "1"},
            }
        elif method == "tools/list":
            if self.catalog_pages is None:
                reply["result"] = {"tools": self.catalog()}
            else:
                cursor = message.get("params", {}).get("cursor")
                reply["result"] = self.catalog_pages[cursor]
        elif method == "tools/call":
            params = message["params"]
            name, args = params["name"], params.get("arguments", {})
            self.calls.append((name, deepcopy(args)))
            if self.http_status:
                status = self.http_status(name, args)
                if status:
                    return httpx2.Response(status, json={"error": "synthetic-sensitive-error"})
            mapping = {
                "get_portfolio_overview": "overview",
                "get_budget_overview": "budget",
                "search_spending": "search",
            }
            value = deepcopy(self.values[mapping.get(name, name)])
            if name == "holdings":
                rows = value["data"]
                offset, limit = args["offset"], args["limit"]
                value["data"] = rows[offset : offset + limit]
                value["meta"] = {
                    "offset": offset,
                    "limit": limit,
                    "total": len(rows),
                    "has_more": offset + limit < len(rows),
                }
            if self.mutate:
                value = self.mutate(name, args, value)
            reply["result"] = {
                "content": [{"type": "text", "text": json.dumps(value)}],
                "structuredContent": value,
                "isError": name == self.tool_error,
            }
        else:
            reply["error"] = {"code": -32601, "message": "Synthetic unsupported method"}
        return httpx2.Response(200, json=reply)

    @asynccontextmanager
    async def http(self):
        async with httpx2.AsyncClient(
            transport=BoundedTransport(httpx2.MockTransport(self.respond))
        ) as client:
            yield client

    def client(self):
        return NativeMcpClient(self.http)
