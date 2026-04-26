"""Typed exceptions raised by the Plaud client."""

from __future__ import annotations


class PlaudError(Exception):
    """Base class for all errors raised by the Plaud client."""


class AuthenticationError(PlaudError):
    """Raised on 401 from the Plaud API. Token missing, expired, or invalid."""


class NotFoundError(PlaudError):
    """Raised on 404 — recording / resource does not exist."""


class APIError(PlaudError):
    """Generic non-2xx API error. Carries status code and raw response body."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        response_body: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


class UploadError(PlaudError):
    """Raised when any step of the multipart upload pipeline fails."""


class AnalysisTimeoutError(PlaudError):
    """Raised when Plaud transcription/summary does not complete in time."""
