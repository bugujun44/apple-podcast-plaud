"""Plaud API client subpackage.

Reusable Plaud client. Public surface:

    from apple_podcast_plaud.plaud import PlaudClient, resolve_token

Designed to be extractable as a standalone ``plaud-py`` package later;
keep this subpackage free of any Apple-Podcasts-specific imports.
"""

from apple_podcast_plaud.plaud.auth import resolve_token
from apple_podcast_plaud.plaud.exceptions import (
    APIError,
    AuthenticationError,
    NotFoundError,
    PlaudError,
    UploadError,
)

__all__ = [
    "APIError",
    "AuthenticationError",
    "NotFoundError",
    "PlaudError",
    "UploadError",
    "resolve_token",
]
