"""Tests for ``TranscriptionsAPI`` (start, status, wait, segments, summary)."""

from __future__ import annotations

import gzip
import json

import pytest
import responses

from apple_podcast_plaud.plaud._endpoints import BASE_URLS
from apple_podcast_plaud.plaud.api.recordings import RecordingsAPI
from apple_podcast_plaud.plaud.api.transcriptions import TranscriptionsAPI
from apple_podcast_plaud.plaud.exceptions import (
    AnalysisTimeoutError,
    NotFoundError,
)
from apple_podcast_plaud.plaud.session import PlaudSession


@pytest.fixture
def api() -> TranscriptionsAPI:
    sess = PlaudSession(token="t", region="apac")
    return TranscriptionsAPI(sess, RecordingsAPI(sess))


@responses.activate
def test_start_sends_language_in_extra_data(api: TranscriptionsAPI) -> None:
    responses.patch(
        BASE_URLS["apac"] + "/file/abc",
        json={"data_file": {"file_id": "abc"}},
    )
    api.start("abc", language="zh")
    sent = json.loads(responses.calls[0].request.body)
    assert sent["extra_data"]["tranConfig"]["language"] == "zh"


@responses.activate
def test_get_status_complete_when_data_result_non_empty(api: TranscriptionsAPI) -> None:
    """Plaud's real shape: ``status: 1`` always; ``data_result`` is the signal."""
    responses.post(
        BASE_URLS["apac"] + "/ai/transsumm/abc",
        json={
            "status": 1,
            "msg": "success",
            "data_result": [
                {"start_time": 0, "end_time": 1000, "content": "hi", "speaker": "S1"},
            ],
        },
    )
    status = api.get_status("abc")
    assert status.complete is True
    assert status.state == 1  # always 1, not a completion signal


@responses.activate
def test_get_status_incomplete_when_data_result_empty(api: TranscriptionsAPI) -> None:
    responses.post(
        BASE_URLS["apac"] + "/ai/transsumm/abc",
        json={"status": 1, "msg": "success", "data_result": []},
    )
    status = api.get_status("abc")
    assert status.complete is False


@responses.activate
def test_get_status_incomplete_when_data_result_missing(api: TranscriptionsAPI) -> None:
    responses.post(
        BASE_URLS["apac"] + "/ai/transsumm/abc",
        json={"status": 1, "msg": "success"},
    )
    status = api.get_status("abc")
    assert status.complete is False


@responses.activate
def test_summary_ready_tracked_separately(api: TranscriptionsAPI) -> None:
    """Transcript can be ready while AI summary is still pending."""
    responses.post(
        BASE_URLS["apac"] + "/ai/transsumm/abc",
        json={
            "status": 1,
            "data_result": [{"start_time": 0, "end_time": 1, "content": "x"}],
            "data_result_summ": [],
        },
    )
    status = api.get_status("abc")
    assert status.complete is True
    assert status.summary_ready is False


@responses.activate
def test_wait_returns_when_complete(api: TranscriptionsAPI) -> None:
    # First call: empty data_result. Second: populated.
    responses.post(
        BASE_URLS["apac"] + "/ai/transsumm/abc",
        json={"status": 1, "data_result": []},
    )
    responses.post(
        BASE_URLS["apac"] + "/ai/transsumm/abc",
        json={
            "status": 1,
            "data_result": [{"start_time": 0, "end_time": 1, "content": "x"}],
        },
    )
    status = api.wait("abc", timeout=5, poll_interval=0)
    assert status.complete


@responses.activate
def test_wait_times_out(api: TranscriptionsAPI) -> None:
    responses.post(
        BASE_URLS["apac"] + "/ai/transsumm/abc",
        json={"status": 1, "data_result": []},
    )
    responses.add_passthru(BASE_URLS["apac"] + "/ai/transsumm/abc")  # extra calls allowed
    with pytest.raises(AnalysisTimeoutError):
        api.wait("abc", timeout=0.1, poll_interval=0.05)


# ---------------------------------------------------------------------------
# get_segments / get_summary — uses get_content_list under the hood
# ---------------------------------------------------------------------------


def _detail_with_content(items: list[dict]) -> dict:
    return {
        "data_file_list": [
            {"file_id": "abc", "file_name": "x", "content_list": items}
        ]
    }


@responses.activate
def test_get_segments_inline_fast_path(api: TranscriptionsAPI) -> None:
    """When transsumm carries data_result inline, segments come from there."""
    inline_payload = {
        "status": 1,
        "data_result": [
            {"start_time": 0, "end_time": 1500, "content": "hi", "speaker": "S1"},
            {"start_time": 1500, "end_time": 4000, "content": "bye", "speaker": "S2"},
        ],
    }
    responses.post(BASE_URLS["apac"] + "/ai/transsumm/abc", json=inline_payload)
    segs = api.get_segments("abc")
    assert len(segs) == 2
    assert segs[0].content == "hi"
    assert segs[0].speaker == "S1"
    # No fallback to /file/list — inline path was sufficient.
    assert all("/ai/transsumm" in c.request.url for c in responses.calls)


@responses.activate
def test_get_segments_falls_back_to_s3_when_inline_empty(api: TranscriptionsAPI) -> None:
    transcript_payload = [
        {"start_time": 0, "end_time": 1500, "content": "hello"},
        {"start_time": 1500, "end_time": 4000, "content": "world"},
    ]
    # transsumm has no inline data_result
    responses.post(
        BASE_URLS["apac"] + "/ai/transsumm/abc",
        json={"status": 1, "data_result": []},
    )
    # S3 path is used instead
    responses.post(
        BASE_URLS["apac"] + "/file/list",
        json=_detail_with_content([
            {
                "data_id": "transaction:abc",
                "data_type": "transaction",
                "task_status": 1,
                "data_link": "https://s3.example/t.json.gz",
            }
        ]),
    )
    responses.get(
        "https://s3.example/t.json.gz",
        body=gzip.compress(json.dumps(transcript_payload).encode()),
    )
    segs = api.get_segments("abc")
    assert len(segs) == 2
    assert segs[0].content == "hello"
    assert segs[1].end_time == 4000


@responses.activate
def test_get_summary_falls_back_to_s3(api: TranscriptionsAPI) -> None:
    """When transsumm has no inline summary block, S3 path is used."""
    summary_payload = {
        "ai_content": "## Summary\nSome markdown.",
        "category": "lecture",
        "header": {"headline": "A talk"},
    }
    # Inline empty
    responses.post(
        BASE_URLS["apac"] + "/ai/transsumm/abc",
        json={"status": 1, "data_result_summ": []},
    )
    # S3 path
    responses.post(
        BASE_URLS["apac"] + "/file/list",
        json=_detail_with_content([
            {
                "data_id": "auto_sum:abc",
                "data_type": "auto_sum_note",
                "task_status": 1,
                "data_link": "https://s3.example/s.json",
            }
        ]),
    )
    responses.get(
        "https://s3.example/s.json",
        body=json.dumps(summary_payload).encode(),
    )
    summary = api.get_summary("abc")
    assert "## Summary" in summary.ai_content
    assert summary.headline == "A talk"
    assert summary.category == "lecture"


@responses.activate
def test_get_segments_raises_when_data_type_missing(api: TranscriptionsAPI) -> None:
    # Inline empty + S3 has no transaction item → both paths fail.
    responses.post(
        BASE_URLS["apac"] + "/ai/transsumm/abc",
        json={"status": 1, "data_result": []},
    )
    responses.post(
        BASE_URLS["apac"] + "/file/list",
        json=_detail_with_content([
            {
                "data_id": "auto_sum:abc",
                "data_type": "auto_sum_note",
                "task_status": 1,
                "data_link": "https://s3.example/s.json",
            }
        ]),
    )
    with pytest.raises(NotFoundError):
        api.get_segments("abc")


@responses.activate
def test_get_summary_inline_path(api: TranscriptionsAPI) -> None:
    """data_result_summ inline carries summ_data as a JSON string."""
    embedded = {
        "ai_content": "## Summary\nMain point.",
        "category": "lecture",
        "header": {"headline": "A title"},
    }
    responses.post(
        BASE_URLS["apac"] + "/ai/transsumm/abc",
        json={
            "status": 1,
            "data_result_summ": [
                {"summary_id": "s1", "summ_data": json.dumps(embedded)}
            ],
        },
    )
    summary = api.get_summary("abc")
    assert summary.headline == "A title"
    assert "Main point" in summary.ai_content
