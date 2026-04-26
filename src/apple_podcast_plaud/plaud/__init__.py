"""Plaud API client subpackage.

Reusable Plaud client. Public surface:

    from apple_podcast_plaud.plaud import PlaudClient, resolve_token

Designed to be extractable as a standalone ``plaud-py`` package later;
keep this subpackage free of any Apple-Podcasts-specific imports.
"""

from apple_podcast_plaud.plaud.auth import (
    decode_jwt_payload,
    infer_region,
    login_with_password,
    resolve_token,
    save_token,
    token_info,
    verify_token,
)
from apple_podcast_plaud.plaud.client import PlaudClient
from apple_podcast_plaud.plaud.exceptions import (
    AnalysisTimeoutError,
    APIError,
    AuthenticationError,
    NotFoundError,
    PlaudError,
    UploadError,
)
from apple_podcast_plaud.plaud.models import (
    AnalysisStatus,
    ContentListItem,
    Recording,
    Summary,
    TranscriptionSegment,
)

__all__ = [
    # client
    "PlaudClient",
    # auth
    "decode_jwt_payload",
    "infer_region",
    "login_with_password",
    "resolve_token",
    "save_token",
    "token_info",
    "verify_token",
    # models
    "AnalysisStatus",
    "ContentListItem",
    "Recording",
    "Summary",
    "TranscriptionSegment",
    # exceptions
    "AnalysisTimeoutError",
    "APIError",
    "AuthenticationError",
    "NotFoundError",
    "PlaudError",
    "UploadError",
]
