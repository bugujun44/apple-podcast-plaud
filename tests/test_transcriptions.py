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
def test_get_status_complete_when_state_is_10(api: TranscriptionsAPI) -> None:
    responses.post(
        BASE_URLS["apac"] + "/ai/transsumm/abc",
        json={"state": 10, "ai_content": "..."},
    )
    status = api.get_status("abc")
    assert status.complete is True
    assert status.state == 10


@responses.activate
def test_get_status_incomplete_when_pending(api: TranscriptionsAPI) -> None:
    responses.post(
        BASE_URLS["apac"] + "/ai/transsumm/abc",
        json={"state": 1},
    )
    status = api.get_status("abc")
    assert status.complete is False


@responses.activate
def test_wait_returns_when_complete(api: TranscriptionsAPI) -> None:
    # First call: pending. Second: complete.
    responses.post(BASE_URLS["apac"] + "/ai/transsumm/abc", json={"state": 1})
    responses.post(BASE_URLS["apac"] + "/ai/transsumm/abc", json={"state": 10})
    status = api.wait("abc", timeout=5, poll_interval=0)
    assert status.complete


@responses.activate
def test_wait_times_out(api: TranscriptionsAPI) -> None:
    responses.post(BASE_URLS["apac"] + "/ai/transsumm/abc", json={"state": 1})
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
def test_get_segments_fetches_transaction_link(api: TranscriptionsAPI) -> None:
    transcript_payload = [
        {"start_time": 0, "end_time": 1500, "content": "hello"},
        {"start_time": 1500, "end_time": 4000, "content": "world"},
    ]
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
def test_get_summary_fetches_auto_sum_note(api: TranscriptionsAPI) -> None:
    summary_payload = {
        "ai_content": "## Summary\nSome markdown.",
        "category": "lecture",
        "header": {"headline": "A talk"},
    }
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
