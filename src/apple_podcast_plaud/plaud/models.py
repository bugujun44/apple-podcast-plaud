"""Pydantic models for the Plaud API surface we care about.

We only model the fields we actually consume — Plaud's responses carry many
more (telemetry, A/B flags, etc.). ``model_config = {"extra": "ignore"}``
keeps us forward-compatible when the server adds new fields.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class _Lenient(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class Recording(_Lenient):
    """A single Plaud recording (file). Returned by list / get / upload."""

    file_id: str = Field(alias="file_id")
    filename: str = Field(default="", alias="file_name")
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

    Plaud doesn't expose a clean "complete" boolean; we infer it from the
    presence of usable result blocks. The raw payload is preserved on
    :attr:`raw` so callers can dig if needed.
    """

    state: int = 0
    raw: dict[str, Any] = Field(default_factory=dict)

    @property
    def complete(self) -> bool:
        # Plaud signals readiness via state==10 and / or non-empty ai_content.
        if self.state == 10:
            return True
        return bool(self.raw.get("ai_content"))

    @classmethod
    def from_response(cls, data: dict[str, Any]) -> "AnalysisStatus":
        return cls(state=int(data.get("state", 0) or 0), raw=data)
