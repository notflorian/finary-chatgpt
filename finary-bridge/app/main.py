"""FastAPI boundary for local diagnostics and normalized snapshots."""

import os
import secrets
from typing import Annotated, Literal, NamedTuple

from fastapi import Depends, FastAPI, Header, Request, status
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from app.config import SERVICE_NAME, SERVICE_VERSION
from app.errors import ErrorDetail, ErrorResponse
from app.mcp_client import McpFailure, NativeMcpClient
from app.mcp_logging import protect_access_logs
from app.mcp_models import McpSnapshotV3
from app.mcp_optional import (
    BudgetResponse,
    GoalsResponse,
    OptionalMcpService,
    PeriodRequest,
    SearchRequest,
    SearchResponse,
)
from app.services.mcp_snapshot_service import McpSnapshotService, paris_now


class HealthResponse(BaseModel):
    """Response returned by the local health endpoint."""

    model_config = ConfigDict(frozen=True)

    status: Literal["ok"] = "ok"
    service: str = SERVICE_NAME
    version: str = SERVICE_VERSION


protect_access_logs()

app = FastAPI(
    title="Finary Bridge",
    version=SERVICE_VERSION,
    description="Local bridge for normalized Finary portfolio data.",
)


class _ApiErrorSpec(NamedTuple):
    status_code: int
    code: str
    message: str
    retryable: bool


_BRIDGE_AUTH_ERROR = _ApiErrorSpec(
    status.HTTP_401_UNAUTHORIZED,
    "BRIDGE_AUTH_FAILED",
    "Bridge authentication failed",
    False,
)


class BridgeAuthenticationError(Exception):
    """Raised when a protected bridge route receives invalid credentials."""


def require_bridge_api_key(
    supplied_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> None:
    """Authorize a snapshot request when bridge API-key protection is enabled."""

    expected_key = os.getenv("FINARY_BRIDGE_API_KEY")
    if not expected_key:
        return
    if not isinstance(supplied_key, str) or not secrets.compare_digest(
        expected_key.encode("utf-8", errors="surrogatepass"),
        supplied_key.encode("utf-8", errors="surrogatepass"),
    ):
        raise BridgeAuthenticationError


def _error_response(spec: _ApiErrorSpec) -> JSONResponse:
    payload = ErrorResponse(
        error=ErrorDetail(
            code=spec.code,
            message=spec.message,
            retryable=spec.retryable,
        )
    )
    return JSONResponse(status_code=spec.status_code, content=payload.model_dump())


@app.exception_handler(BridgeAuthenticationError)
async def handle_bridge_authentication_error(
    request: Request, exception: BridgeAuthenticationError
) -> JSONResponse:
    """Reject unauthorized bridge requests without exposing credential details."""

    del request, exception
    return _error_response(_BRIDGE_AUTH_ERROR)


@app.get("/health", response_model=HealthResponse, status_code=status.HTTP_200_OK)
def get_health() -> HealthResponse:
    """Return service metadata without contacting any upstream system."""

    return HealthResponse()


def get_authenticated_mcp_client(
    _: Annotated[None, Depends(require_bridge_api_key)],
) -> NativeMcpClient:
    """Construct the official MCP client only after bridge authorization."""
    return NativeMcpClient()


@app.exception_handler(McpFailure)
async def handle_mcp_error(request: Request, exception: McpFailure) -> JSONResponse:
    del request
    code = (
        400
        if exception.code == "MCP_INVALID_ARGUMENT"
        else 503
        if exception.code in {"MCP_AUTH_UNAVAILABLE", "MCP_CAPABILITY_UNAVAILABLE"}
        else 504
        if exception.code == "MCP_TIMEOUT"
        else 502
    )
    return _error_response(
        _ApiErrorSpec(code, exception.code, exception.message, exception.retryable)
    )


@app.exception_handler(RequestValidationError)
async def handle_request_error(request: Request, exception: RequestValidationError) -> JSONResponse:
    if request.url.path.startswith("/v3/"):
        return await handle_mcp_error(request, McpFailure("MCP_INVALID_ARGUMENT"))
    return await request_validation_exception_handler(request, exception)


@app.get("/v3/snapshot", response_model=McpSnapshotV3)
async def get_snapshot_v3(
    client: Annotated[NativeMcpClient, Depends(get_authenticated_mcp_client)],
) -> McpSnapshotV3:
    return await McpSnapshotService(client).snapshot()


@app.get("/v3/budget", response_model=BudgetResponse)
async def get_budget_v3(
    client: Annotated[NativeMcpClient, Depends(get_authenticated_mcp_client)],
    request: Annotated[PeriodRequest, Depends()],
) -> BudgetResponse:
    return await OptionalMcpService(client).budget(request, paris_now())


@app.get("/v3/spending-search", response_model=SearchResponse)
async def get_spending_search_v3(
    client: Annotated[NativeMcpClient, Depends(get_authenticated_mcp_client)],
    request: Annotated[SearchRequest, Depends()],
) -> SearchResponse:
    return await OptionalMcpService(client).search(request, paris_now())


@app.get("/v3/goals", response_model=GoalsResponse)
async def get_goals_v3(
    client: Annotated[NativeMcpClient, Depends(get_authenticated_mcp_client)],
) -> GoalsResponse:
    return await OptionalMcpService(client).goals(paris_now())
