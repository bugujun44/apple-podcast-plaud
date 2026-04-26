"""Tests for ``RecordingsAPI`` (list, get, get_audio_url, upload)."""

from __future__ import annotations

from pathlib import Path

import pytest
import responses

from apple_podcast_plaud.plaud._endpoints import BASE_URLS
from apple_podcast_plaud.plaud.api.recordings import RecordingsAPI
from apple_podcast_plaud.plaud.exceptions import NotFoundError, UploadError
from apple_podcast_plaud.plaud.session import PlaudSession


@pytest.fixture
def api() -> RecordingsAPI:
    return RecordingsAPI(PlaudSession(token="t", region="apac"))


@responses.activate
def test_list_returns_recordings(api: RecordingsAPI) -> None:
    responses.get(
        BASE_URLS["apac"] + "/file/simple/web",
        json={
            "data_file_list": [
                {
                    "file_id": "abc",
                    "file_name": "Test",
                    "duration": 60.0,
                    "start_time": 1700000000000,
                    "is_trash": False,
                    "is_trans": True,
                    "is_summary": True,
                }
            ]
        },
    )
    out = api.list(limit=10)
    assert len(out) == 1
    assert out[0].file_id == "abc"
    assert out[0].is_trans


@responses.activate
def test_get_raw_404(api: RecordingsAPI) -> None:
    responses.post(BASE_URLS["apac"] + "/file/list", json={"data_file_list": []})
    with pytest.raises(NotFoundError):
        api.get_raw("does-not-exist")


@responses.activate
def test_get_content_list_parses_items(api: RecordingsAPI) -> None:
    responses.post(
        BASE_URLS["apac"] + "/file/list",
        json={
            "data_file_list": [
                {
                    "file_id": "abc",
                    "file_name": "Test",
                    "content_list": [
                        {
                            "data_id": "transaction:abc",
                            "data_type": "transaction",
                            "task_status": 1,
                            "data_link": "https://s3/transcript.json",
                        },
                        {
                            "data_id": "auto_sum:abc",
                            "data_type": "auto_sum_note",
                            "task_status": 1,
                            "data_link": "https://s3/summary.json",
                        },
                    ],
                }
            ]
        },
    )
    items = api.get_content_list("abc")
    assert {i.data_type for i in items} == {"transaction", "auto_sum_note"}


@responses.activate
def test_get_audio_url_extracts_temp_url(api: RecordingsAPI) -> None:
    responses.get(
        BASE_URLS["apac"] + "/file/temp-url/abc",
        json={"data": {"temp_url": "https://s3/audio.m4a"}},
    )
    assert api.get_audio_url("abc") == "https://s3/audio.m4a"


@responses.activate
def test_get_audio_url_handles_top_level_temp_url(api: RecordingsAPI) -> None:
    responses.get(
        BASE_URLS["apac"] + "/file/temp-url/abc",
        json={"temp_url": "https://s3/audio.m4a"},
    )
    assert api.get_audio_url("abc") == "https://s3/audio.m4a"


# ---------------------------------------------------------------------------
# Upload — tests the 4-step pipeline end-to-end against a mock server
# ---------------------------------------------------------------------------


@responses.activate
def test_upload_4_step_pipeline(api: RecordingsAPI, tmp_path: Path) -> None:
    audio = tmp_path / "x.m4a"
    audio.write_bytes(b"fake-audio-bytes")

    responses.post(
        BASE_URLS["apac"] + "/file/get_upload_presigned_url",
        json={
            "data": {
                "part_urls": ["https://s3-upload.example/part1"],
                "upload_id": "uid-1",
                "object_name": "obj/abc.m4a",
            }
        },
    )
    responses.put(
        "https://s3-upload.example/part1",
        status=200,
        headers={"ETag": '"deadbeef"'},
    )
    responses.post(BASE_URLS["apac"] + "/file/merge_multipart", json={"status": 0})
    responses.post(
        BASE_URLS["apac"] + "/file/confirm_upload",
        json={
            "data": {
                "file_id": "new-id",
                "file_name": "Imported.m4a",
                "duration": 0.0,
                "start_time": 1700000000000,
                "is_trash": False,
            }
        },
    )

    rec = api.upload(audio, name="Imported.m4a")
    assert rec.file_id == "new-id"
    # Sanity: every step was hit
    paths_hit = [c.request.path_url for c in responses.calls]
    assert any("/get_upload_presigned_url" in p for p in paths_hit)
    assert any("/merge_multipart" in p for p in paths_hit)
    assert any("/confirm_upload" in p for p in paths_hit)


def test_upload_rejects_unknown_extension(api: RecordingsAPI, tmp_path: Path) -> None:
    weird = tmp_path / "x.ogg"
    weird.write_bytes(b"x")
    with pytest.raises(UploadError):
        api.upload(weird)


def test_upload_rejects_missing_file(api: RecordingsAPI, tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        api.upload(tmp_path / "nope.m4a")


@responses.activate
def test_upload_s3_failure_surfaces_as_upload_error(api: RecordingsAPI, tmp_path: Path) -> None:
    audio = tmp_path / "x.m4a"
    audio.write_bytes(b"fake")
    responses.post(
        BASE_URLS["apac"] + "/file/get_upload_presigned_url",
        json={
            "data": {
                "part_urls": ["https://s3-upload.example/part1"],
                "upload_id": "uid-1",
                "object_name": "obj/abc.m4a",
            }
        },
    )
    responses.put("https://s3-upload.example/part1", status=403, body="Forbidden")
    with pytest.raises(UploadError):
        api.upload(audio)
