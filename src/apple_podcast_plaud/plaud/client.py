"""High-level :class:`PlaudClient` — what users actually instantiate.

Wires together a region-aware :class:`PlaudSession`, a
:class:`RecordingsAPI`, and a :class:`TranscriptionsAPI` from a single
``token``. Region is auto-inferred from the JWT unless overridden.
"""

from __future__ import annotations

from apple_podcast_plaud.plaud.api.recordings import RecordingsAPI
from apple_podcast_plaud.plaud.api.transcriptions import TranscriptionsAPI
from apple_podcast_plaud.plaud.auth import infer_region, resolve_token
from apple_podcast_plaud.plaud.session import PlaudSession


class PlaudClient:
    """Top-level entry point.

    Usage:

        from apple_podcast_plaud.plaud import PlaudClient

        client = PlaudClient()  # picks up token via auth.resolve_token()
        for rec in client.recordings.list(limit=5):
            print(rec.file_id, rec.filename)

    If your account is in a non-US region the JWT's ``region`` claim is
    used automatically; you can also set it explicitly:

        client = PlaudClient(region="apac")
    """

    def __init__(
        self,
        token: str | None = None,
        *,
        region: str | None = None,
    ) -> None:
        self.token = resolve_token(token)
        self.region = region or infer_region(self.token)
        self.session = PlaudSession(self.token, region=self.region)
        self.recordings = RecordingsAPI(self.session)
        self.transcriptions = TranscriptionsAPI(self.session, self.recordings)

    def __repr__(self) -> str:
        return f"PlaudClient(region={self.region!r})"
