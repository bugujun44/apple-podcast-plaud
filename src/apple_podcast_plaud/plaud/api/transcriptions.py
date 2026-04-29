"""Transcriptions: kick off, poll, fetch verbatim segments + AI summary.

The reverse-engineered TS toolkit's ``transcript`` command picks the
*longest* string off ``pre_download_content_list`` and prints it. That
turns out to be the AI summary, not the verbatim transcript — a confusing
default. We expose the two as **distinct** methods:

- :meth:`get_segments` — verbatim transcript (``data_type == "transaction"``)
- :meth:`get_summary`  — AI summary (``data_type == "auto_sum_note"``)

Both deserialize the gzipped JSON Plaud stores on S3.
"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Any

from apple_podcast_plaud.plaud._endpoints import (
    P_AI_TRANSSUMM,
    P_FILE_DETAIL,
)
from apple_podcast_plaud.plaud.exceptions import (
    AnalysisTimeoutError,
    APIError,
    NotFoundError,
)
from apple_podcast_plaud.plaud.models import (
    AnalysisStatus,
    Summary,
    TranscriptionSegment,
)

if TYPE_CHECKING:
    from apple_podcast_plaud.plaud.api.recordings import RecordingsAPI
    from apple_podcast_plaud.plaud.session import PlaudSession


# data_type values in content_list
DT_TRANSCRIPT = "transaction"  # yes, that's how Plaud spells it
DT_SUMMARY = "auto_sum_note"
DT_OUTLINE = "outline"


class TranscriptionsAPI:
    """Trigger and retrieve transcription artifacts."""

    def __init__(self, session: "PlaudSession", recordings: "RecordingsAPI") -> None:
        self._s = session
        self._recs = recordings

    # ------------------------------------------------------------------
    # Trigger / poll
    # ------------------------------------------------------------------

    def start(self, file_id: str, *, language: str = "en") -> dict[str, Any]:
        """Tell Plaud to (re)analyse a recording.

        Args:
            file_id: Recording ID returned by :meth:`upload`.
            language: ISO code — ``en``, ``zh``, ``ja``, ``ru``, ``ko``, etc.

        For freshly uploaded files Plaud usually starts analysis automatically;
        this PATCH is mainly useful to switch language or restart with a
        different config.
        """
        data = self._s.patch(
            f"{P_FILE_DETAIL}/{file_id}",
            json={
                "extra_data": {
                    "tranConfig": {
                        "language": language,
                        "type_type": "system",
                        "type": "REASONING-NOTE",
                        "diarization": 1,
                        "llm": "auto",
                    }
                }
            },
        )
        return data.get("data_file") or data.get("data") or data

    def get_status(self, file_id: str, *, language: str = "en") -> AnalysisStatus:
        """One-shot status poll. Cheap; safe to call in a loop."""
        data = self._s.post(
            f"{P_AI_TRANSSUMM}/{file_id}",
            json={
                "is_reload": 0,
                "summ_type": "REASONING-NOTE",
                "summ_type_type": "system",
                "info": json.dumps({
                    "language": language,
                    "diarization": 1,
                    "llm": "auto",
                }),
                "support_mul_summ": True,
            },
        )
        return AnalysisStatus.from_response(data)

    def wait(
        self,
        file_id: str,
        *,
        language: str = "en",
        timeout: int = 600,
        poll_interval: int = 10,
    ) -> AnalysisStatus:
        """Block until analysis completes, return the final status.

        Raises:
            AnalysisTimeoutError: if analysis hasn't finished within ``timeout``
                seconds. The recording is unchanged server-side; you can call
                ``wait`` again later to keep polling.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            status = self.get_status(file_id, language=language)
            if status.complete:
                return status
            time.sleep(poll_interval)
        raise AnalysisTimeoutError(
            f"Plaud analysis for {file_id} did not complete within {timeout}s"
        )

    # ------------------------------------------------------------------
    # Fetch artifacts
    # ------------------------------------------------------------------

    def _fetch_data_link(self, file_id: str, data_type: str) -> dict[str, Any]:
        """Resolve the S3 link for ``data_type`` on a recording, fetch + parse JSON.

        Raises:
            NotFoundError: if no item with that data_type exists yet
                (most often: transcription is still running).
        """
        items = self._recs.get_content_list(file_id)
        hit = next((it for it in items if it.data_type == data_type), None)
        if hit is None:
            avail = sorted({it.data_type for it in items})
            raise NotFoundError(
                f"No content_list item with data_type={data_type!r} "
                f"on recording {file_id}. Available: {avail}"
            )
        if not hit.data_link:
            raise NotFoundError(
                f"data_type={data_type!r} on {file_id} has no data_link "
                f"(task_status={hit.task_status})"
            )
        body = self._s.get_raw_bytes(hit.data_link)
        try:
            return json.loads(body)
        except json.JSONDecodeError as e:
            raise APIError(f"Plaud returned non-JSON for {data_type}: {body[:200]!r}") from e

    def get_segments(
        self,
        file_id: str,
        *,
        language: str = "en",
    ) -> list[TranscriptionSegment]:
        """Verbatim transcript as a list of timed segments.

        Plaud delivers segments via one of two paths depending on the
        recording's age and category:

        - **Inline** in the ``/ai/transsumm/{id}`` poll response under
          ``data_result``. Used by newer recordings (observed on APAC).
        - **S3-linked** via ``content_list[data_type='transaction']`` →
          gzipped JSON blob on S3. Used by older recordings.

        We try inline first (one round-trip, always present when the
        recording is "complete" by our definition) and fall back to S3.
        """
        # Path 1: inline
        status = self.get_status(file_id, language=language)
        inline = status.raw.get("data_result")
        if isinstance(inline, list) and inline:
            return [TranscriptionSegment.model_validate(s) for s in inline]

        # Path 2: S3 link
        try:
            payload = self._fetch_data_link(file_id, DT_TRANSCRIPT)
        except NotFoundError as e:
            raise NotFoundError(
                f"No transcript found for {file_id} via either inline "
                f"data_result or content_list[transaction]. "
                f"(Last error: {e})"
            ) from None
        if not isinstance(payload, list):
            raise APIError(
                f"Expected a JSON array for transaction data; got {type(payload).__name__}"
            )
        return [TranscriptionSegment.model_validate(seg) for seg in payload]

    def get_summary(
        self,
        file_id: str,
        *,
        language: str = "en",
    ) -> Summary:
        """AI-generated summary (markdown). Inline first, then S3 fallback.

        The inline shape is ``data_result_summ`` — a list of ``{summary_id,
        summ_data}`` rows where ``summ_data`` itself is a JSON string of
        the same shape :class:`Summary` understands. If neither inline
        nor S3 has anything, raises :class:`NotFoundError`.
        """
        import json as _json

        # Path 1: inline
        status = self.get_status(file_id, language=language)
        inline = status.raw.get("data_result_summ")
        if isinstance(inline, list) and inline:
            first = inline[0]
            blob = first.get("summ_data") if isinstance(first, dict) else None
            if isinstance(blob, str):
                try:
                    return Summary.from_payload(_json.loads(blob))
                except _json.JSONDecodeError:
                    pass  # fall through to S3
            elif isinstance(blob, dict):
                return Summary.from_payload(blob)

        # Path 2: S3 link
        payload = self._fetch_data_link(file_id, DT_SUMMARY)
        if not isinstance(payload, dict):
            raise APIError(
                f"Expected a JSON object for auto_sum_note; got {type(payload).__name__}"
            )
        return Summary.from_payload(payload)

    def get_outline(self, file_id: str) -> dict[str, Any]:
        """Chapter-style outline. Format is loose; we return the raw dict."""
        payload = self._fetch_data_link(file_id, DT_OUTLINE)
        if not isinstance(payload, dict):
            raise APIError(
                f"Expected a JSON object for outline; got {type(payload).__name__}"
            )
        return payload
