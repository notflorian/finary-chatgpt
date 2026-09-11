"""Native official MCP transport, catalog discovery and sanitized tool boundary."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import httpx2
from jsonschema import Draft202012Validator
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.types import CallToolResult, TextContent

from app.mcp_validation import CONTRACT, validate

MCP_URL = "https://public-api.finary.com/mcp"
LIMITS = CONTRACT["transport_policy"]["limits"]


class McpFailure(Exception):
    """Fixed, allowlisted failures with no retained upstream text or exceptions."""

    def __init__(self, code: str = "MCP_MALFORMED_RESPONSE") -> None:
        messages = CONTRACT["transport_policy"]["error_messages"]
        if code not in messages:
            code = "MCP_PROTOCOL_ERROR"
        self.code = code
        self.message: str = messages[code]["message"]
        self.retryable: bool = messages[code]["retryable"]
        super().__init__(self.message)


def sanitized_failure(error: BaseException, fallback: str = "MCP_PROTOCOL_ERROR") -> McpFailure:
    """Recover only allowlisted failure types across SDK task-group boundaries."""
    pending = [error]
    seen: set[int] = set()
    selected = fallback
    while pending and len(seen) < 64:
        item = pending.pop()
        if id(item) in seen:
            continue
        seen.add(id(item))
        if isinstance(item, McpFailure) and item.code != "MCP_PROTOCOL_ERROR":
            return McpFailure(item.code)
        if isinstance(item, httpx2.HTTPStatusError):
            if item.response.status_code in {401, 403}:
                selected = "MCP_AUTH_UNAVAILABLE"
            elif item.response.status_code == 429:
                selected = "MCP_RATE_LIMITED"
        if isinstance(item, BaseExceptionGroup):
            pending.extend(item.exceptions)
        for nested in (item.__cause__, item.__context__):
            if nested is not None:
                pending.append(nested)
    return McpFailure(selected)


def checked(name: str, value: Any) -> Any:
    try:
        validate(name, value)
        return value
    except (ValueError, TypeError, RecursionError):
        raise McpFailure() from None


def local_schema(schema: Any) -> None:
    """Tool schemas may not cause JSON Schema to retrieve arbitrary URLs."""
    if isinstance(schema, dict):
        for name, value in schema.items():
            if name in {"$ref", "$dynamicRef", "$id"} and (
                not isinstance(value, str) or not value.startswith("#")
            ):
                raise McpFailure("MCP_CAPABILITY_UNAVAILABLE")
            local_schema(value)
    elif isinstance(schema, list):
        for value in schema:
            local_schema(value)


def _object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name, value in pairs:
        if name in result:
            raise ValueError("Duplicate JSON member")
        result[name] = value
    return result


def decode_result(result: CallToolResult) -> dict[str, Any]:
    if result.is_error:
        raise McpFailure("MCP_TOOL_ERROR")
    try:
        if len(result.model_dump_json().encode()) > LIMITS["max_response_bytes"]:
            raise ValueError
        structured = result.structured_content
        text_payloads = []
        for block in result.content:
            if not isinstance(block, TextContent):
                raise ValueError
            text_payloads.append(json.loads(block.text, object_pairs_hook=_object_pairs))
        if len(text_payloads) > 1:
            raise ValueError
        if (
            structured is not None
            and text_payloads
            and json.dumps(structured, sort_keys=True, allow_nan=False)
            != json.dumps(text_payloads[0], sort_keys=True, allow_nan=False)
        ):
            raise ValueError
        payload = (
            structured if structured is not None else text_payloads[0] if text_payloads else None
        )
        if not isinstance(payload, dict):
            raise ValueError
        return payload
    except (ValueError, TypeError, RecursionError):
        raise McpFailure() from None


class LimitedStream(httpx2.AsyncByteStream):
    def __init__(self, stream: httpx2.AsyncByteStream, content_type: str) -> None:
        self.stream = stream
        self.content_type = content_type

    async def __aiter__(self) -> AsyncIterator[bytes]:
        total = 0
        pending = b""
        event_data: list[bytes] = []
        is_json = self.content_type.split(";")[0] == "application/json"
        is_sse = self.content_type.split(";")[0] == "text/event-stream"
        async for chunk in self.stream:
            total += len(chunk)
            if total > LIMITS["max_response_bytes"]:
                raise McpFailure()
            pending += chunk
            if is_json:
                continue
            if is_sse:
                lines = pending.split(b"\n")
                pending = lines.pop()
                for line in lines:
                    line = line.rstrip(b"\r")
                    if line.startswith(b"data:"):
                        event_data.append(line[5:].lstrip(b" "))
                    elif not line:
                        payload = b"\n".join(event_data)
                        if payload.strip():
                            self.validate_json(payload)
                        event_data.clear()
            else:
                pending = b""
            yield chunk
        if is_json and pending:
            self.validate_json(pending)
            yield pending
        elif is_sse:
            if pending.startswith(b"data:"):
                event_data.append(pending[5:].lstrip(b" "))
            payload = b"\n".join(event_data)
            if payload.strip():
                self.validate_json(payload)

    @staticmethod
    def invalid_constant(value: str) -> None:
        del value
        raise ValueError("Non-finite JSON constant")

    @staticmethod
    def validate_json(value: bytes) -> None:
        try:
            json.loads(
                value,
                object_pairs_hook=_object_pairs,
                parse_constant=LimitedStream.invalid_constant,
            )
        except (ValueError, RecursionError):
            raise McpFailure() from None

    async def aclose(self) -> None:
        await self.stream.aclose()


class BoundedTransport(httpx2.AsyncBaseTransport):
    """Bound raw bytes before SDK parsing; only read-only MCP requests may retry."""

    def __init__(self, transport: httpx2.AsyncBaseTransport | None = None) -> None:
        self.transport = transport or httpx2.AsyncHTTPTransport(retries=0)

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        request.headers["Accept-Encoding"] = "identity"
        retry_read = False
        if str(request.url) == MCP_URL and request.method == "POST":
            try:
                body = json.loads(request.content)
                retry_read = body.get("method") in {
                    "initialize",
                    "server/discover",
                    "tools/list",
                    "tools/call",
                }
            except (ValueError, httpx2.RequestNotRead):
                pass
        attempts = LIMITS["max_attempts_per_call"] if retry_read else 1
        for attempt in range(attempts):
            try:
                response = await self.transport.handle_async_request(request)
            except (httpx2.ConnectError, httpx2.TimeoutException):
                if attempt + 1 == attempts:
                    raise McpFailure("MCP_TIMEOUT") from None
            else:
                if response.status_code not in {429, 502, 503, 504} or attempt + 1 == attempts:
                    if response.status_code == 429:
                        await response.aclose()
                        raise McpFailure("MCP_RATE_LIMITED")
                    if response.headers.get("content-encoding", "identity") != "identity":
                        await response.aclose()
                        raise McpFailure()
                    if not isinstance(response.stream, httpx2.AsyncByteStream):
                        raise McpFailure()
                    response.stream = LimitedStream(
                        response.stream, response.headers.get("content-type", "")
                    )
                    return response
                await response.aclose()
            await asyncio.sleep(0.25 * 2**attempt)
        raise McpFailure("MCP_TIMEOUT")

    async def aclose(self) -> None:
        await self.transport.aclose()


def suppress_sdk_diagnostics() -> None:
    """SDK exceptions may include tokens or response bodies; never forward them."""
    for name in ("mcp", "httpx2", "httpcore2"):
        logger = logging.getLogger(name)
        logger.handlers = [logging.NullHandler()]
        logger.propagate = False


@dataclass
class McpSession:
    client: Client
    catalog: dict[str, Any]

    @classmethod
    async def discover(cls, client: Client, required: tuple[str, ...]) -> McpSession:
        if not client.protocol_version or client.server_capabilities.tools is None:
            raise McpFailure("MCP_PROTOCOL_ERROR")
        catalog: dict[str, Any] = {}
        cursors: set[str] = set()
        cursor = None
        for _ in range(100):
            async with asyncio.timeout(LIMITS["call_timeout_seconds"]):
                page = await client.list_tools(cursor=cursor)
            if len(page.model_dump_json().encode()) > LIMITS["max_response_bytes"]:
                raise McpFailure()
            for tool in page.tools:
                if tool.name in catalog or len(catalog) >= 1000:
                    raise McpFailure("MCP_PROTOCOL_ERROR")
                if tool.name in CONTRACT["capabilities"]:
                    local_schema(tool.input_schema)
                    Draft202012Validator.check_schema(tool.input_schema)
                    if tool.input_schema.get("type") != "object":
                        raise McpFailure("MCP_CAPABILITY_UNAVAILABLE")
                    if tool.output_schema is not None:
                        local_schema(tool.output_schema)
                        Draft202012Validator.check_schema(tool.output_schema)
                catalog[tool.name] = tool
            cursor = page.next_cursor
            if cursor is None:
                break
            if not cursor or cursor in cursors:
                raise McpFailure("MCP_PROTOCOL_ERROR")
            cursors.add(cursor)
        else:
            raise McpFailure("MCP_PROTOCOL_ERROR")
        if any(name not in catalog for name in required):
            raise McpFailure("MCP_CAPABILITY_UNAVAILABLE")
        if "holdings" in catalog:
            schema = catalog["holdings"].input_schema
            props = schema.get("properties", {})
            probe = {"account_id": "synthetic-account", "limit": 100, "offset": 0}
            validator = Draft202012Validator(schema)
            if any(name not in props for name in probe) or not validator.is_valid(probe):
                raise McpFailure("MCP_CAPABILITY_UNAVAILABLE")
            for name, invalid in (("account_id", 123), ("limit", "100"), ("offset", -1)):
                if validator.is_valid({**probe, name: invalid}):
                    raise McpFailure("MCP_CAPABILITY_UNAVAILABLE")
        return cls(client, catalog)

    async def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name not in self.catalog or name not in CONTRACT["capabilities"]:
            raise McpFailure("MCP_CAPABILITY_UNAVAILABLE")
        if "prompt" in arguments or name == "simulate_compound_interest":
            raise McpFailure("MCP_INVALID_ARGUMENT")
        tool = self.catalog[name]
        if not Draft202012Validator(tool.input_schema).is_valid(arguments):
            raise McpFailure("MCP_CAPABILITY_UNAVAILABLE")
        try:
            async with asyncio.timeout(LIMITS["call_timeout_seconds"]):
                result = await self.client.call_tool(name, arguments)
            payload = decode_result(result)
            if tool.output_schema is not None and not Draft202012Validator(
                tool.output_schema
            ).is_valid(payload):
                raise McpFailure()
            reference = CONTRACT["capabilities"][name]["output_schema"].split("/")[-1]
            return checked(reference, payload)  # type: ignore[no-any-return]
        except McpFailure:
            raise
        except TimeoutError:
            raise McpFailure("MCP_TIMEOUT") from None
        except Exception as error:
            raise sanitized_failure(error) from None


class NativeMcpClient:
    """One bounded native session per read; OAuth bootstrap is a separate command."""

    def __init__(self, auth_factory: Callable[..., Any] | None = None) -> None:
        self.auth_factory = auth_factory

    @asynccontextmanager
    async def session(self, required: tuple[str, ...]) -> AsyncIterator[McpSession]:
        from app.mcp_auth import authorized_http

        suppress_sdk_diagnostics()
        factory = self.auth_factory or authorized_http
        try:
            async with asyncio.timeout(LIMITS["collection_timeout_seconds"]), factory() as http:
                transport = streamable_http_client(MCP_URL, http_client=http)
                async with Client(
                    transport, read_timeout_seconds=LIMITS["call_timeout_seconds"], cache=None
                ) as client:
                    yield await McpSession.discover(client, required)
        except McpFailure:
            raise
        except TimeoutError:
            raise McpFailure("MCP_TIMEOUT") from None
        except Exception as error:
            raise sanitized_failure(error) from None
