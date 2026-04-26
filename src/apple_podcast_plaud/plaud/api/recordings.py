"""Recordings: list, get, upload, audio download.

Upload is a 4-step pipeline that mirrors what web.plaud.ai does:

    1. POST  /file/get_upload_presigned_url   → presigned S3 PUT URL
    2. PUT   <presigned-url>                  → upload bytes
    3. POST  /file/merge_multipart            → tell Plaud to assemble
    4. POST  /file/confirm_upload             → register the new recording

This is reverse-engineered from the public web app and may break without
notice. Not endorsed by Plaud.
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from apple_podcast_plaud.plaud._endpoints import (
    P_FILE_CONFIRM,
    P_FILE_LIST,
    P_FILE_MERGE,
    P_FILE_SIMPLE,
    P_FILE_TEMP_URL,
    P_FILE_UPLOAD_URL,
)
from apple_podcast_plaud.plaud.exceptions import NotFoundError, UploadError
from apple_podcast_plaud.plaud.models import ContentListItem, Recording

if TYPE_CHECKING:
    from apple_podcast_plaud.plaud.session import PlaudSession

# Plaud uses ".asr" as their device's native compressed format; if we ever see
# a file uploaded with that suffix we want it tagged as OPUS server-side.
_OPUS_SUFFIXES = {".asr", ".opus"}
_AUDIO_SUFFIXES = {".mp3", ".m4a", ".aac", ".wav", ".mp4"}


class RecordingsAPI:
    """All recording-level operations."""

    def __init__(self, session: "PlaudSession") -> None:
        self._s = session

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def list(
        self,
        *,
        limit: int = 50,
        skip: int = 0,
        sort_by: str = "start_time",
        descending: bool = True,
    ) -> list[Recording]:
        """Return the most recent ``limit`` recordings, freshest first by default."""
        data = self._s.get(
            P_FILE_SIMPLE,
            params={
                "skip": skip,
                "limit": limit,
                "is_trash": 0,
                "sort_by": sort_by,
                "is_desc": str(descending).lower(),
            },
        )
        return [Recording.model_validate(f) for f in data.get("data_file_list", [])]

    def get_raw(self, file_id: str) -> dict[str, Any]:
        """Full raw detail blob for a single recording — includes ``content_list``."""
        data = self._s.post(P_FILE_LIST, json=[file_id], timeout=60)
        files = data.get("data_file_list") or []
        if not files:
            raise NotFoundError(f"Recording not found: {file_id}")
        return files[0]

    def get(self, file_id: str) -> Recording:
        """Validated :class:`Recording` model for a single recording."""
        return Recording.model_validate(self.get_raw(file_id))

    def get_content_list(self, file_id: str) -> list[ContentListItem]:
        """List the artifact rows attached to a recording (transcript, summary, etc.)."""
        raw = self.get_raw(file_id)
        return [ContentListItem.model_validate(it) for it in raw.get("content_list", [])]

    # ------------------------------------------------------------------
    # Audio
    # ------------------------------------------------------------------

    def get_audio_url(self, file_id: str) -> str:
        """A short-lived presigned S3 URL for the original audio file."""
        data = self._s.get(f"{P_FILE_TEMP_URL}/{file_id}")
        url = (data.get("data") or {}).get("temp_url") or data.get("temp_url")
        if not url:
            raise NotFoundError(f"No temp_url for {file_id}")
        return url

    # ------------------------------------------------------------------
    # Upload
    # ------------------------------------------------------------------

    def upload(
        self,
        file_path: str | Path,
        *,
        name: str | None = None,
    ) -> Recording:
        """Upload an audio file to Plaud, returning the newly created Recording.

        The file is sent in a single 4-step multipart pipeline. For a 30-min
        m4a (~15 MB) the whole flow is typically 5-10 seconds on a good link.
        """
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        suffix = file_path.suffix.lower()
        if suffix in _OPUS_SUFFIXES:
            file_type = "OPUS"
        elif suffix in _AUDIO_SUFFIXES:
            file_type = "MP3"
        else:
            raise UploadError(
                f"Unsupported audio extension {suffix!r}. "
                f"Allowed: {sorted(_AUDIO_SUFFIXES | _OPUS_SUFFIXES)}"
            )

        file_size = file_path.stat().st_size

        # Step 1 — presigned URL
        presign = self._s.post(
            P_FILE_UPLOAD_URL,
            json={"filesize": file_size, "file_type": file_type},
        )
        slot = presign.get("data") or presign
        try:
            upload_url = slot["part_urls"][0]
            upload_id = slot["upload_id"]
            object_name = slot["object_name"]
        except (KeyError, IndexError, TypeError) as e:
            raise UploadError(f"Unexpected presigned-URL response: {presign}") from e

        # Step 2 — PUT to S3
        with open(file_path, "rb") as f:
            put_resp = self._s.put_raw(
                upload_url,
                data=f,
                headers={"Content-Type": "application/octet-stream"},
            )
        if put_resp.status_code != 200:
            raise UploadError(
                f"S3 PUT failed: {put_resp.status_code} {put_resp.text[:200]}"
            )
        etag = put_resp.headers.get("ETag", "").strip('"')

        # Step 3 — merge multipart
        self._s.post(
            P_FILE_MERGE,
            json={
                "upload_id": upload_id,
                "object_name": object_name,
                "parts": [{"Etag": etag, "PartNumber": 1}],
            },
        )

        # Step 4 — confirm
        if name is None:
            name = f"Upload {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        ts_ms = int(time.time() * 1000)
        confirm = self._s.post(
            P_FILE_CONFIRM,
            json={
                "upload_id": upload_id,
                "object_name": object_name,
                "scene": 101,
                "is_tmp": 0,
                "support_mul_summ": True,
                "file_type": file_type,
                "filename": name,
                "start_time": ts_ms,
                "session_id": int(ts_ms / 1000),
                "serial_number": str(uuid.uuid4()),
            },
        )
        return Recording.model_validate(confirm.get("data") or confirm)
