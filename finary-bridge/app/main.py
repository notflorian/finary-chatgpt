"""FastAPI application entry point."""

from typing import Literal

from fastapi import FastAPI, status
from pydantic import BaseModel, ConfigDict

from app.config import SERVICE_NAME, SERVICE_VERSION


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


@app.get("/health", response_model=HealthResponse, status_code=status.HTTP_200_OK)
def get_health() -> HealthResponse:
    """Return service metadata without contacting any upstream system."""

    return HealthResponse()
