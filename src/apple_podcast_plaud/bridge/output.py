"""Render transcripts + summary to disk and emit a JSON envelope.

Keeping this isolated from the Plaud / TTML tracks lets us reuse the same
output layout regardless of how the segments were produced.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from apple_podcast_plaud.plaud.models import Summary, TranscriptionSegment

DEFAULT_ROOT = Path.home() / "Documents" / "podcasts"

_SAFE = re.compile(r'[/\\:?*<>|"\x00-\x1f]+')


def _slug(s: str, *, max_len: int = 60) -> str:
    s = _SAFE.sub("_", s).strip().strip(".")
    return s[:max_len] or "untitled"


def _fmt_ts(ms: int) -> str:
    s = ms // 1000
    if s >= 3600:
        return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"
    return f"{s // 60:02d}:{s % 60:02d}"


@dataclass
class TranscribeResult:
    """In-memory result a track produces; ``write_artifacts`` consumes this."""

    podcast: str
    episode: str
    language: str
    segments: list[TranscriptionSegment]
    summary: Summary | None
    source: str  # e.g. "plaud" or "apple-ttml"
    plaud_recording_id: str | None = None
    duration_sec: int = 0


def _segments_to_md(segments: list[TranscriptionSegment]) -> str:
    lines = []
    for seg in segments:
        content = (seg.content or "").strip()
        if not content:
            continue
        speaker = f"({seg.speaker}) " if seg.speaker else ""
        lines.append(f"**[{_fmt_ts(seg.start_time)}]** {speaker}{content}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_artifacts(
    result: TranscribeResult,
    *,
    out_root: Path = DEFAULT_ROOT,
    out_dir: Path | None = None,
    elapsed_sec: int = 0,
    today: date | None = None,
) -> dict[str, Any]:
    """Write transcript / summary / metadata + return a JSON envelope.

    Args:
        result: filled-in :class:`TranscribeResult`.
        out_root: parent directory; ignored if ``out_dir`` is given.
        out_dir: explicit output dir; created if missing.
        elapsed_sec: total wall time for the run (informational).
        today: date stamp; defaults to today (callers can pin for tests).

    Returns:
        The JSON envelope dict — caller decides what to do (stdout, file, …).
    """
    today = today or date.today()
    if out_dir is None:
        slug = _slug(f"{result.podcast}-{result.episode}")
        out_dir = out_root / f"{today.isoformat()}-{slug}"
    out_dir.mkdir(parents=True, exist_ok=True)

    transcript_md = out_dir / "transcript.md"
    summary_md = out_dir / "summary.md"
    raw_json = out_dir / "transcript.raw.json"
    metadata_json = out_dir / "metadata.json"

    # transcript.md
    frontmatter = (
        "---\n"
        f"podcast: {result.podcast}\n"
        f"episode: {result.episode}\n"
        f"language: {result.language}\n"
        f"source: {result.source}\n"
        + (
            f"plaud_recording_id: {result.plaud_recording_id}\n"
            if result.plaud_recording_id
            else ""
        )
        + f"transcribed_at: {today.isoformat()}\n"
        + "---\n\n"
    )
    body = (
        f"# {result.episode}\n\n"
        f"> 节目：{result.podcast}  ·  转写日期：{today.isoformat()}  "
        f"·  语言：{result.language}  ·  来源：{result.source}\n\n"
        "## 逐字稿\n\n"
        + _segments_to_md(result.segments)
    )
    transcript_md.write_text(frontmatter + body, encoding="utf-8")

    # summary.md
    if result.summary and result.summary.ai_content.strip():
        summary_md.write_text(result.summary.ai_content, encoding="utf-8")
    else:
        summary_md.write_text("_(no summary available)_\n", encoding="utf-8")

    # raw.json — segments only, no metadata
    raw_json.write_text(
        json.dumps(
            [seg.model_dump() for seg in result.segments],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    # metadata.json — denormalised summary of everything
    meta_payload = {
        "podcast": result.podcast,
        "episode": result.episode,
        "language": result.language,
        "source": result.source,
        "plaud_recording_id": result.plaud_recording_id,
        "duration_sec": result.duration_sec,
        "segment_count": len(result.segments),
        "transcribed_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    metadata_json.write_text(
        json.dumps(meta_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    envelope = {
        "status": "ok",
        "podcast": result.podcast,
        "episode": result.episode,
        "language": result.language,
        "duration_sec": result.duration_sec,
        "segment_count": len(result.segments),
        "out_dir": str(out_dir),
        "files": {
            "transcript_md": str(transcript_md),
            "summary_md": str(summary_md),
            "raw_json": str(raw_json),
            "metadata_json": str(metadata_json),
        },
        "source": result.source,
        "plaud_recording_id": result.plaud_recording_id,
        "elapsed_sec": elapsed_sec,
    }
    return envelope


def result_to_dict(r: TranscribeResult) -> dict[str, Any]:
    """Helpful for debugging — flat dict view."""
    d = asdict(r)
    d["segments"] = [s.model_dump() for s in r.segments]
    if r.summary is not None:
        d["summary"] = r.summary.model_dump()
    return d
