"""Plaud track: upload an m4a → wait for transcription → fetch artifacts."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from apple_podcast_plaud.bridge.output import TranscribeResult
from apple_podcast_plaud.plaud import PlaudClient
from apple_podcast_plaud.plaud.exceptions import NotFoundError
from apple_podcast_plaud.plaud.models import Summary

ProgressFn = Callable[[str], None]


def _noop(_: str) -> None:
    pass


def transcribe_via_plaud(
    client: PlaudClient,
    audio_path: Path,
    *,
    podcast_title: str,
    episode_title: str,
    language: str,
    upload_name: str | None = None,
    poll_interval: int = 10,
    timeout: int = 1200,
    progress: ProgressFn = _noop,
) -> TranscribeResult:
    """Run a full Plaud transcription cycle and return an in-memory result.

    Args:
        client: Authenticated :class:`PlaudClient`.
        audio_path: Local m4a / mp3 — will be uploaded as-is.
        podcast_title: Used to label the recording on Plaud and in metadata.
        episode_title: Used to label the recording on Plaud and in metadata.
        language: Plaud language code (``zh`` / ``en`` / ``ja`` / ...).
        upload_name: Override the displayed name on Plaud. Defaults to a
            ``"podcast — episode"`` join.
        poll_interval: Seconds between status checks while waiting.
        timeout: Max wait in seconds.
        progress: Callable for status messages — connect to ``click.echo``
            in CLI usage; left a no-op for library callers.

    Returns:
        :class:`TranscribeResult` with segments + (optional) summary.
    """
    upload_name = upload_name or f"{podcast_title} — {episode_title}"
    progress(f"Uploading {audio_path.name} to Plaud as {upload_name!r}…")
    rec = client.recordings.upload(audio_path, name=upload_name)
    progress(f"Uploaded. recording_id={rec.file_id}; waiting for transcription "
             f"(language={language})…")

    client.transcriptions.wait(
        rec.file_id,
        language=language,
        timeout=timeout,
        poll_interval=poll_interval,
    )
    progress("Plaud finished analysis. Fetching segments + summary…")

    segments = client.transcriptions.get_segments(rec.file_id)

    # Summary may not exist for very short recordings — degrade gracefully.
    try:
        summary: Summary | None = client.transcriptions.get_summary(rec.file_id)
    except NotFoundError:
        summary = None

    duration_sec = rec.duration_seconds
    if not duration_sec and segments:
        duration_sec = segments[-1].end_time // 1000

    return TranscribeResult(
        podcast=podcast_title,
        episode=episode_title,
        language=language,
        segments=segments,
        summary=summary,
        source="plaud",
        plaud_recording_id=rec.file_id,
        duration_sec=duration_sec,
    )
