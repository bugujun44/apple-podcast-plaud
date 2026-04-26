"""Tests for bridge modules: language detection, output rendering, CLI shape."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner

from apple_podcast_plaud.bridge import language as lang
from apple_podcast_plaud.bridge.cli import main as cli_main
from apple_podcast_plaud.bridge.output import (
    TranscribeResult,
    write_artifacts,
)
from apple_podcast_plaud.bridge.tracks.plaud_track import transcribe_via_plaud
from apple_podcast_plaud.plaud.models import (
    Recording,
    Summary,
    TranscriptionSegment,
)


# ---------------------------------------------------------------------------
# language detection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("titles", "expected"),
    [
        (("逆商：我们如何应对坏事件",), "zh"),
        (("Acquired: NVIDIA",), "en"),
        (("ロジカルな思考について",), "ja"),
        (("주식 투자 입문",), "ko"),
        (("高情商沟通话术", "320 逆商"), "zh"),
        (("", ""), "en"),
        (("Mixed title 中文 + English",), "zh"),  # CJK present anywhere
    ],
)
def test_language_detection(titles, expected) -> None:
    assert lang.detect(*titles) == expected


# ---------------------------------------------------------------------------
# output / artifact writing
# ---------------------------------------------------------------------------


def _result_fixture(segments: list[TranscriptionSegment] | None = None) -> TranscribeResult:
    return TranscribeResult(
        podcast="Test Podcast",
        episode="Test Episode 001",
        language="zh",
        segments=segments
        or [
            TranscriptionSegment(start_time=0, end_time=5000, content="开场白。"),
            TranscriptionSegment(start_time=5000, end_time=15000, content="正文一。"),
        ],
        summary=Summary(ai_content="## TL;DR\n\nSome markdown.", headline="A talk"),
        source="plaud",
        plaud_recording_id="rec-123",
        duration_sec=15,
    )


def test_write_artifacts_creates_all_files(tmp_path: Path) -> None:
    res = _result_fixture()
    envelope = write_artifacts(res, out_root=tmp_path, today=date(2026, 4, 26))

    out_dir = Path(envelope["out_dir"])
    assert out_dir.is_dir()
    for key in ("transcript_md", "summary_md", "raw_json", "metadata_json"):
        assert Path(envelope["files"][key]).exists()

    # Check frontmatter + segment formatting
    md = (out_dir / "transcript.md").read_text(encoding="utf-8")
    assert "podcast: Test Podcast" in md
    assert "language: zh" in md
    assert "**[00:00]**" in md
    assert "**[00:05]**" in md

    # JSON envelope shape
    assert envelope["status"] == "ok"
    assert envelope["language"] == "zh"
    assert envelope["segment_count"] == 2
    assert envelope["plaud_recording_id"] == "rec-123"
    assert envelope["source"] == "plaud"


def test_write_artifacts_handles_no_summary(tmp_path: Path) -> None:
    res = _result_fixture()
    res.summary = None
    envelope = write_artifacts(res, out_root=tmp_path, today=date(2026, 4, 26))
    assert "(no summary available)" in Path(envelope["files"]["summary_md"]).read_text()


def test_write_artifacts_explicit_out_dir_wins(tmp_path: Path) -> None:
    explicit = tmp_path / "custom" / "subdir"
    res = _result_fixture()
    envelope = write_artifacts(res, out_dir=explicit)
    assert Path(envelope["out_dir"]) == explicit


# ---------------------------------------------------------------------------
# tracks/plaud_track — happy path with mocked client
# ---------------------------------------------------------------------------


def test_transcribe_via_plaud_drives_client(tmp_path: Path) -> None:
    audio = tmp_path / "x.m4a"
    audio.write_bytes(b"audio")
    rec = Recording(file_id="rec-9", file_name="x.m4a", duration=30.0)
    segments = [
        TranscriptionSegment(start_time=0, end_time=2000, content="hi"),
        TranscriptionSegment(start_time=2000, end_time=5000, content="bye"),
    ]
    summary = Summary(ai_content="## TLDR", headline="A")

    client = MagicMock()
    client.recordings.upload.return_value = rec
    client.transcriptions.wait.return_value = MagicMock()
    client.transcriptions.get_segments.return_value = segments
    client.transcriptions.get_summary.return_value = summary

    result = transcribe_via_plaud(
        client,
        audio,
        podcast_title="P",
        episode_title="E",
        language="zh",
        poll_interval=0,
        timeout=5,
    )
    assert result.plaud_recording_id == "rec-9"
    assert result.language == "zh"
    assert len(result.segments) == 2
    assert result.summary is not None
    assert result.summary.headline == "A"

    client.recordings.upload.assert_called_once()
    client.transcriptions.wait.assert_called_once()


# ---------------------------------------------------------------------------
# CLI smoke tests — verify command tree wires up
# ---------------------------------------------------------------------------


def test_cli_has_expected_commands() -> None:
    runner = CliRunner()
    result = runner.invoke(cli_main, ["--help"])
    assert result.exit_code == 0
    assert "auth" in result.output
    assert "list-podcasts" in result.output
    assert "transcribe" in result.output


def test_cli_auth_subcommands_present() -> None:
    runner = CliRunner()
    result = runner.invoke(cli_main, ["auth", "--help"])
    assert result.exit_code == 0
    assert "login" in result.output
    assert "set-token" in result.output
    assert "status" in result.output
    assert "logout" in result.output


def test_cli_transcribe_help_mentions_keyword() -> None:
    runner = CliRunner()
    result = runner.invoke(cli_main, ["transcribe", "--help"])
    assert result.exit_code == 0
    assert "KEYWORD" in result.output
