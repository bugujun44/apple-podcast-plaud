"""Tests for the MCP server tools."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

from apple_podcast_plaud.bridge.apple_podcasts import Episode
from apple_podcast_plaud.mcp.server import auth_login, auth_status, list_podcasts, transcribe
from apple_podcast_plaud.plaud.exceptions import AuthenticationError, PlaudError

# ---------------------------------------------------------------------------
# list_podcasts
# ---------------------------------------------------------------------------


def _make_episode(title: str = "Test Episode", podcast: str = "Test Podcast") -> Episode:
    m4a = MagicMock(spec=Path)
    m4a.stat.return_value = MagicMock(st_size=50 * 1024 * 1024)
    return Episode(
        podcast_title=podcast,
        episode_title=title,
        m4a_path=m4a,
        import_date_unix=int(datetime(2026, 4, 30, 10, 0).timestamp()),
    )


@patch("apple_podcast_plaud.mcp.server.ap.list_downloaded")
def test_list_podcasts_no_keyword(mock_list) -> None:
    mock_list.return_value = [_make_episode()]
    result = list_podcasts("", 10)
    assert len(result) == 1
    assert result[0]["podcast_title"] == "Test Podcast"
    assert result[0]["episode_title"] == "Test Episode"
    assert result[0]["file_size_mb"] == 50.0
    mock_list.assert_called_once_with(limit=10)


@patch("apple_podcast_plaud.mcp.server.ap.find_by_keyword")
def test_list_podcasts_with_keyword(mock_find) -> None:
    mock_find.return_value = [_make_episode("AI Episode")]
    result = list_podcasts("AI", 5)
    assert len(result) == 1
    assert result[0]["episode_title"] == "AI Episode"
    mock_find.assert_called_once_with("AI", limit=5)


@patch("apple_podcast_plaud.mcp.server.ap.list_downloaded")
def test_list_podcasts_empty(mock_list) -> None:
    mock_list.return_value = []
    result = list_podcasts("", 10)
    assert result == []


# ---------------------------------------------------------------------------
# auth_status
# ---------------------------------------------------------------------------


@patch("apple_podcast_plaud.mcp.server.resolve_token")
def test_auth_status_no_token(mock_resolve) -> None:
    mock_resolve.side_effect = AuthenticationError("No token")
    result = auth_status()
    assert result["authenticated"] is False
    assert "auth_login" in result["message"]


@patch("apple_podcast_plaud.mcp.server.verify_token")
@patch("apple_podcast_plaud.mcp.server.token_info")
@patch("apple_podcast_plaud.mcp.server.resolve_token")
def test_auth_status_valid_token(mock_resolve, mock_info, mock_verify) -> None:
    mock_resolve.return_value = "fake.jwt.token"
    mock_info.return_value = {
        "region": "us",
        "user_id": "user123",
        "expires_in_days": 30,
        "expires_at": int(datetime(2026, 5, 30).timestamp()),
    }
    mock_verify.return_value = True
    result = auth_status()
    assert result["authenticated"] is True
    assert result["region"] == "us"
    assert result["expires_in_days"] == 30


@patch("apple_podcast_plaud.mcp.server.verify_token")
@patch("apple_podcast_plaud.mcp.server.token_info")
@patch("apple_podcast_plaud.mcp.server.resolve_token")
def test_auth_status_expired_token(mock_resolve, mock_info, mock_verify) -> None:
    mock_resolve.return_value = "fake.jwt.token"
    mock_info.return_value = {
        "region": "us",
        "user_id": "user123",
        "expires_in_days": -5,
        "expires_at": int(datetime(2026, 4, 25).timestamp()),
    }
    mock_verify.return_value = False
    result = auth_status()
    assert result["authenticated"] is False
    assert result["server_verified"] is False


# ---------------------------------------------------------------------------
# auth_login
# ---------------------------------------------------------------------------


@patch("apple_podcast_plaud.mcp.server.token_info")
@patch("apple_podcast_plaud.mcp.server.save_token")
@patch("apple_podcast_plaud.mcp.server.login_with_password")
def test_auth_login_success(mock_login, mock_save, mock_info) -> None:
    mock_login.return_value = "new.jwt.token"
    mock_info.return_value = {"region": "us", "expires_in_days": 60}
    result = auth_login("test@example.com", "password123")
    assert result["success"] is True
    assert result["region"] == "us"
    mock_save.assert_called_once_with("new.jwt.token")


@patch("apple_podcast_plaud.mcp.server.login_with_password")
def test_auth_login_wrong_password(mock_login) -> None:
    mock_login.side_effect = AuthenticationError("wrong account or password")
    result = auth_login("test@example.com", "wrong")
    assert result["success"] is False
    assert result["error"] == "auth_failed"
    assert "Google/Apple" in result["message"]


@patch("apple_podcast_plaud.mcp.server.login_with_password")
def test_auth_login_network_error(mock_login) -> None:
    mock_login.side_effect = PlaudError("Connection timeout")
    result = auth_login("test@example.com", "password123")
    assert result["success"] is False
    assert result["error"] == "network_error"


# ---------------------------------------------------------------------------
# transcribe
# ---------------------------------------------------------------------------


@patch("apple_podcast_plaud.mcp.server.resolve_token")
def test_transcribe_no_auth(mock_resolve) -> None:
    mock_resolve.side_effect = AuthenticationError("No token")
    result = transcribe("podcast keyword")
    assert result["error"] == "not_authenticated"
    assert "auth_login" in result["message"]


@patch("apple_podcast_plaud.mcp.server.ap.list_downloaded")
@patch("apple_podcast_plaud.mcp.server.ap.find_by_keyword")
@patch("apple_podcast_plaud.mcp.server.resolve_token")
def test_transcribe_no_match(mock_resolve, mock_find, mock_list) -> None:
    mock_resolve.return_value = "fake.jwt.token"
    mock_find.return_value = []
    mock_list.return_value = [_make_episode("Available One")]
    result = transcribe("nonexistent")
    assert result["error"] == "not_found"
    assert "Available One" in result["message"]


@patch("apple_podcast_plaud.mcp.server.write_artifacts")
@patch("apple_podcast_plaud.mcp.server.transcribe_via_plaud")
@patch("apple_podcast_plaud.mcp.server.PlaudClient")
@patch("apple_podcast_plaud.mcp.server.ap.find_by_keyword")
@patch("apple_podcast_plaud.mcp.server.resolve_token")
def test_transcribe_success(
    mock_resolve, mock_find, mock_client, mock_transcribe, mock_write, tmp_path
) -> None:
    mock_resolve.return_value = "fake.jwt.token"

    ep = _make_episode("中文播客第一期", "科技周刊")
    mock_find.return_value = [ep]

    mock_result = MagicMock()
    mock_transcribe.return_value = mock_result

    transcript_file = tmp_path / "transcript.md"
    transcript_file.write_text("# Transcript\nHello world")
    summary_file = tmp_path / "summary.md"
    summary_file.write_text("Summary of episode")

    mock_write.return_value = {
        "status": "ok",
        "podcast": "科技周刊",
        "episode": "中文播客第一期",
        "language": "zh",
        "duration_sec": 1800,
        "segment_count": 42,
        "out_dir": str(tmp_path),
        "files": {
            "transcript_md": str(transcript_file),
            "summary_md": str(summary_file),
            "raw_json": str(tmp_path / "raw.json"),
            "metadata_json": str(tmp_path / "metadata.json"),
        },
        "source": "plaud",
        "plaud_recording_id": "rec123",
        "elapsed_sec": 180,
    }

    result = transcribe("中文播客")
    assert result["status"] == "ok"
    assert result["podcast"] == "科技周刊"
    assert result["transcript"] == "# Transcript\nHello world"
    assert result["summary"] == "Summary of episode"
    assert result["duration_seconds"] == 1800
    assert result["segment_count"] == 42
