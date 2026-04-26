"""Per-resource API wrappers (recordings, transcriptions)."""

from apple_podcast_plaud.plaud.api.recordings import RecordingsAPI
from apple_podcast_plaud.plaud.api.transcriptions import TranscriptionsAPI

__all__ = ["RecordingsAPI", "TranscriptionsAPI"]
