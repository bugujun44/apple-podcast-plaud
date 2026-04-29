"""Pydantic models for the Plaud API surface we care about.

We only model the fields we actually consume — Plaud's responses carry many
more (telemetry, A/B flags, etc.). ``model_config = {"extra": "ignore"}``
keeps us forward-compatible when the server adds new fields.
"""

from __future__ import annotations

from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class _Lenient(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class Recording(_Lenient):
    """A single Plaud recording (file). Returned by list / get / upload.

    Plaud is inconsistent about field naming across endpoints:
    ``/file/simple/web`` returns ``file_id``/``file_name`` while
    ``/file/confirm_upload`` returns ``id``/``filename``. We accept either
    via :class:`pydantic.AliasChoices` so the same model parses both.
    """

    file_id: str = Field(validation_alias=AliasChoices("file_id", "id"))
    filename: str = Field(
        default="",
        validation_alias=AliasChoices("file_name", "filename"),
    )
    duration: float = 0.0  # seconds
    start_time: int = 0  # unix epoch ms
    is_trash: bool = False
    is_trans: bool = False  # transcription has been generated
    is_summary: bool = False  # AI summary has been generated
    scene: int | None = None


class TranscriptionSegment(_Lenient):
    """One verbatim segment from the ``transaction`` data_type."""

    start_time: int  # ms from start of recording
    end_time: int  # ms
    content: str
    speaker: str | None = None
    speaker_id: int | None = Field(default=None, alias="speaker_id")


class Summary(_Lenient):
    """Plaud AI summary (the ``auto_sum_note`` data_type, parsed)."""

    ai_content: str = ""  # markdown body
    category: str = ""
    headline: str = ""

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "Summary":
        """Build from the JSON Plaud stores on S3 for ``auto_sum_note``.

        The shape is roughly ``{"ai_content": "...", "header": {"headline": "..."},
        "category": "..."}``. Headline lives one level deep.
        """
        header = payload.get("header") or {}
        return cls(
            ai_content=payload.get("ai_content", ""),
            category=payload.get("category", ""),
            headline=header.get("headline", ""),
        )


class ContentListItem(_Lenient):
    """One entry in ``recording.content_list`` — discriminated by ``data_type``.

    Common ``data_type`` values:
        - ``transaction`` — verbatim transcript segments JSON
        - ``auto_sum_note`` — AI summary markdown JSON
        - ``outline`` — chapter outline JSON
        - ``source_transaction`` / ``source_outline`` — raw audio links
    """

    data_id: str
    data_type: str
    task_status: int = 0  # 1 == ready
    data_link: str | None = None
    data_title: str = ""


class AnalysisStatus(_Lenient):
    """Polling response from ``/ai/transsumm/{file_id}``.

    Plaud doesn't expose a clean "complete" boolean. The signals we have
    actually observed in production:

    - Top-level ``status`` is ``1`` for any successful response (does NOT
      mean transcription has completed — just that the poll RPC succeeded).
    - When transcription is done, ``data_result`` is a non-empty array of
      verbatim segments (with ``content`` / ``start_time`` / ``end_time`` /
      ``speaker`` fields). Until then it's empty / missing.
    - When the AI summary is done, ``data_result_summ`` is non-empty.

    We treat "transcription ready" as the completion bar — the AI summary
    arrives slightly later but the verbatim transcript is the user's main
    deliverable. Callers needing the summary can poll a bit longer
    or simply call ``get_summary`` and tolerate a NotFoundError.
    """

    raw: dict[str, Any] = Field(default_factory=dict)

    @property
    def complete(self) -> bool:
        result = self.raw.get("data_result")
        return isinstance(result, list) and len(result) > 0

    @property
    def summary_ready(self) -> bool:
        summ = self.raw.get("data_result_summ")
        return isinstance(summ, list) and len(summ) > 0 or bool(summ)

    @property
    def state(self) -> int:
        """Plaud's ``status`` field — kept for backward compat; rarely useful.

        Will be ``1`` on every healthy response, regardless of whether
        transcription has finished. Use :attr:`complete` to gate work.
        """
        return int(self.raw.get("status", 0) or 0)

    @classmethod
    def from_response(cls, data: dict[str, Any]) -> "AnalysisStatus":
        return cls(raw=data)
