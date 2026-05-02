"""MCP server exposing podcast transcription tools.

Tools:
    - list_podcasts: query Apple Podcasts' local SQLite for downloaded episodes
    - transcribe: upload an episode to Plaud and wait for transcription
    - auth_status: check whether a valid Plaud token exists
    - auth_login: exchange email + password for a Plaud token
"""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from apple_podcast_plaud.bridge import apple_podcasts as ap
from apple_podcast_plaud.bridge import language as lang
from apple_podcast_plaud.bridge.output import write_artifacts
from apple_podcast_plaud.bridge.tracks.plaud_track import transcribe_via_plaud
from apple_podcast_plaud.plaud import (
    PlaudClient,
    login_with_password,
    save_token,
    token_info,
    verify_token,
)
from apple_podcast_plaud.plaud.auth import resolve_token
from apple_podcast_plaud.plaud.exceptions import AuthenticationError, PlaudError

mcp = FastMCP(
    "podcast-transcribe",
    instructions=(
        "Transcribe podcast episodes downloaded in Apple Podcasts on macOS. "
        "Use list_podcasts to find episodes, then transcribe to get the text. "
        "If not authenticated, call auth_login first."
    ),
)


@mcp.tool()
def list_podcasts(keyword: str = "", limit: int = 10) -> list[dict]:
    """List downloaded Apple Podcasts episodes on this Mac.

    Args:
        keyword: Optional substring to filter by podcast or episode title.
            Leave empty to list the most recent downloads.
        limit: Max number of episodes to return (default 10).

    Returns:
        List of episodes with podcast_title, episode_title, date, and file size.
    """
    if keyword:
        episodes = ap.find_by_keyword(keyword, limit=limit)
    else:
        episodes = ap.list_downloaded(limit=limit)

    return [
        {
            "podcast_title": ep.podcast_title,
            "episode_title": ep.episode_title,
            "date": datetime.fromtimestamp(ep.import_date_unix).strftime("%Y-%m-%d %H:%M"),
            "file_size_mb": round(ep.m4a_path.stat().st_size / (1024 * 1024), 1),
        }
        for ep in episodes
    ]


@mcp.tool()
def transcribe(keyword: str, language: str | None = None, timeout: int = 1200) -> dict:
    """Transcribe a downloaded podcast episode via Plaud AI.

    Finds the episode by keyword match against podcast/episode titles, uploads
    the audio to Plaud, waits for AI transcription (typically 2-5 minutes for a
    30-minute episode), and returns the full transcript text.

    Requires Plaud authentication. If you get an authentication error, call
    auth_login first to set up credentials.

    Args:
        keyword: Search term to match against podcast or episode titles.
            The most recent match is used if multiple episodes match.
        language: Override language detection. Use "zh" for Chinese, "en" for
            English, "ja" for Japanese, "ko" for Korean. If omitted, detected
            automatically from the episode title.
        timeout: Max seconds to wait for Plaud analysis (default 1200).

    Returns:
        Dict with transcript text, summary, file paths, and metadata.
    """
    try:
        resolve_token()
    except AuthenticationError:
        return {
            "error": "not_authenticated",
            "message": (
                "No Plaud token found. Please call auth_login with your Plaud "
                "email and password to authenticate first. If your account uses "
                "Google/Apple sign-in only, you'll need to set a password via "
                "'Forgot password' at web.plaud.ai first."
            ),
        }

    matches = ap.find_by_keyword(keyword, limit=20)
    if not matches:
        available = ap.list_downloaded(limit=5)
        hint = (
            " Available episodes: " + ", ".join(e.episode_title for e in available)
            if available
            else ""
        )
        return {
            "error": "not_found",
            "message": f"No downloaded episode matches '{keyword}'.{hint}",
        }

    ep = matches[0]
    detected = lang.detect(ep.podcast_title, ep.episode_title)
    final_lang = language or detected

    client = PlaudClient()
    started = time.monotonic()

    result = transcribe_via_plaud(
        client,
        ep.m4a_path,
        podcast_title=ep.podcast_title,
        episode_title=ep.episode_title,
        language=final_lang,
        timeout=timeout,
    )

    envelope = write_artifacts(
        result,
        elapsed_sec=int(time.monotonic() - started),
    )

    transcript_text = ""
    transcript_path = envelope["files"]["transcript_md"]
    if Path(transcript_path).exists():
        transcript_text = Path(transcript_path).read_text(encoding="utf-8")

    summary_text = ""
    summary_path = envelope["files"]["summary_md"]
    if Path(summary_path).exists():
        summary_text = Path(summary_path).read_text(encoding="utf-8")

    return {
        "status": "ok",
        "podcast": envelope["podcast"],
        "episode": envelope["episode"],
        "language": envelope["language"],
        "duration_seconds": envelope["duration_sec"],
        "segment_count": envelope["segment_count"],
        "transcript": transcript_text,
        "summary": summary_text,
        "files": envelope["files"],
        "elapsed_seconds": envelope["elapsed_sec"],
    }


@mcp.tool()
def auth_status() -> dict:
    """Check whether Plaud authentication is configured and valid.

    Returns current auth state including region, expiry, and whether the
    server still accepts the token.
    """
    try:
        token = resolve_token()
    except AuthenticationError:
        return {
            "authenticated": False,
            "message": "No token found. Use auth_login to authenticate.",
        }

    info = token_info(token)

    try:
        server_ok = verify_token(token, region=info["region"])
    except PlaudError:
        server_ok = None

    return {
        "authenticated": True if server_ok else False,
        "region": info["region"],
        "user_id": info["user_id"],
        "expires_in_days": info["expires_in_days"],
        "expires_at": (
            datetime.fromtimestamp(info["expires_at"]).strftime("%Y-%m-%d %H:%M")
            if info["expires_at"]
            else None
        ),
        "server_verified": server_ok,
    }


@mcp.tool()
def auth_login(email: str, password: str) -> dict:
    """Log in to Plaud with email and password to obtain an API token.

    The token is saved locally and used automatically for future transcribe
    calls. This only works for accounts that have an email+password set.
    Accounts created via Google/Apple sign-in only will get a 'wrong password'
    error — those users need to set a password first via 'Forgot password' at
    web.plaud.ai, or manually extract a token from the browser.

    Args:
        email: Plaud account email address.
        password: Plaud account password.

    Returns:
        Success status with region and token expiry info.
    """
    try:
        token = login_with_password(email, password)
    except AuthenticationError as e:
        return {
            "success": False,
            "error": "auth_failed",
            "message": (
                f"{e} — If this account uses Google/Apple sign-in, you have no "
                "Plaud password. Go to web.plaud.ai → 'Forgot password' to set "
                "one first, then try again."
            ),
        }
    except PlaudError as e:
        return {
            "success": False,
            "error": "network_error",
            "message": str(e),
        }

    save_token(token)
    info = token_info(token)

    return {
        "success": True,
        "region": info["region"],
        "expires_in_days": info["expires_in_days"],
        "message": f"Logged in successfully. Token valid for {info['expires_in_days']} days.",
    }
