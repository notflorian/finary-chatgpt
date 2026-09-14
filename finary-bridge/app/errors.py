"""Shared sanitized HTTP error contract."""

from pydantic import BaseModel, ConfigDict, Field


class ErrorDetail(BaseModel):
    """Stable machine-readable API error detail."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    retryable: bool


class ErrorResponse(BaseModel):
    """Project-wide API error envelope."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    error: ErrorDetail
