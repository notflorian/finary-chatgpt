"""FastAPI boundary for local diagnostics and normalized snapshots."""

from functools import lru_cache
from typing import Annotated, Final, Literal, NamedTuple

from fastapi import Depends, FastAPI, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from app.config import SERVICE_NAME, SERVICE_VERSION
from app.finary_client import (
    FinaryApiClient,
    FinaryAuthenticationError,
    FinaryClient,
    FinaryClientError,
    FinaryFeatureUnavailableError,
    FinaryMalformedResponseError,
    FinaryUpstreamError,
    FinaryUpstreamTimeoutError,
)
from app.models import ErrorDetail, ErrorResponse, PortfolioSnapshot, PortfolioSnapshotV2
from app.normalizer import SnapshotNormalizationError
from app.services.snapshot_service import SnapshotService


class HealthResponse(BaseModel):
    """Response returned by the local health endpoint."""

    model_config = ConfigDict(frozen=True)

    status: Literal["ok"] = "ok"
    service: str = SERVICE_NAME
    version: str = SERVICE_VERSION


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


_UPSTREAM_ERROR_SPECS: Final[tuple[tuple[type[FinaryClientError], _ApiErrorSpec], ...]] = (
    (
        FinaryAuthenticationError,
        _ApiErrorSpec(
            status.HTTP_502_BAD_GATEWAY,
            "FINARY_AUTH_FAILED",
            "Unable to authenticate with Finary",
            False,
        ),
    ),
    (
        FinaryUpstreamTimeoutError,
        _ApiErrorSpec(
            status.HTTP_504_GATEWAY_TIMEOUT,
            "FINARY_TIMEOUT",
            "Finary request timed out",
            True,
        ),
    ),
    (
        FinaryMalformedResponseError,
        _ApiErrorSpec(
            status.HTTP_502_BAD_GATEWAY,
            "FINARY_MALFORMED_RESPONSE",
            "Finary returned a malformed response",
            False,
        ),
    ),
    (
        FinaryFeatureUnavailableError,
        _ApiErrorSpec(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "FINARY_FEATURE_UNAVAILABLE",
            "Required Finary data is unavailable",
            False,
        ),
    ),
    (
        FinaryUpstreamError,
        _ApiErrorSpec(
            status.HTTP_502_BAD_GATEWAY,
            "FINARY_UPSTREAM_ERROR",
            "Unable to retrieve data from Finary",
            True,
        ),
    ),
)


@lru_cache(maxsize=1)
def get_finary_client() -> FinaryClient:
    """Reuse one non-interactive adapter and refresh lock for the process lifetime."""

    return FinaryApiClient.from_environment()


def get_snapshot_service(
    client: Annotated[FinaryClient, Depends(get_finary_client)],
) -> SnapshotService:
    """Create the request-scoped snapshot orchestration service."""

    return SnapshotService(client)


def _error_response(spec: _ApiErrorSpec) -> JSONResponse:
    payload = ErrorResponse(
        error=ErrorDetail(
            code=spec.code,
            message=spec.message,
            retryable=spec.retryable,
        )
    )
    return JSONResponse(status_code=spec.status_code, content=payload.model_dump())


@app.exception_handler(FinaryClientError)
async def handle_finary_error(request: Request, exception: FinaryClientError) -> JSONResponse:
    """Translate adapter exceptions without exposing upstream messages."""

    del request
    for error_type, spec in _UPSTREAM_ERROR_SPECS:
        if isinstance(exception, error_type):
            return _error_response(spec)
    return _error_response(
        _ApiErrorSpec(
            status.HTTP_502_BAD_GATEWAY,
            "FINARY_UPSTREAM_ERROR",
            "Unable to retrieve data from Finary",
            True,
        )
    )


@app.exception_handler(SnapshotNormalizationError)
async def handle_snapshot_validation_error(
    request: Request, exception: SnapshotNormalizationError
) -> JSONResponse:
    """Return a stable error when upstream data cannot be normalized safely."""

    del request, exception
    return _error_response(
        _ApiErrorSpec(
            status.HTTP_502_BAD_GATEWAY,
            "SNAPSHOT_VALIDATION_FAILED",
            "Unable to build a valid portfolio snapshot",
            False,
        )
    )


@app.get("/health", response_model=HealthResponse, status_code=status.HTTP_200_OK)
def get_health() -> HealthResponse:
    """Return service metadata without contacting any upstream system."""

    return HealthResponse()


@app.get(
    "/v1/snapshot",
    response_model=PortfolioSnapshot,
    status_code=status.HTTP_200_OK,
)
def get_snapshot(
    service: Annotated[SnapshotService, Depends(get_snapshot_service)],
) -> PortfolioSnapshot:
    """Return one validated snapshot containing no private upstream payloads."""

    return service.get_snapshot()


@app.get(
    "/v2/snapshot",
    response_model=PortfolioSnapshotV2,
    status_code=status.HTTP_200_OK,
)
def get_snapshot_v2(
    service: Annotated[SnapshotService, Depends(get_snapshot_service)],
) -> PortfolioSnapshotV2:
    """Return a coverage-aware snapshot without private upstream payloads."""

    return service.get_snapshot_v2()
