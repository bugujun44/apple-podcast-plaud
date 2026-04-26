"""Tests for the PlaudSession HTTP wrapper.

Uses ``responses`` for HTTP mocking. No real network traffic is generated.
"""

from __future__ import annotations

import gzip

import pytest
import responses

from apple_podcast_plaud.plaud._endpoints import BASE_URLS
from apple_podcast_plaud.plaud.exceptions import (
    APIError,
    AuthenticationError,
    NotFoundError,
)
from apple_podcast_plaud.plaud.session import PlaudSession


@pytest.fixture
def session() -> PlaudSession:
    return PlaudSession(token="dummy-token", region="apac")


@responses.activate
def test_get_returns_parsed_json(session: PlaudSession) -> None:
    url = BASE_URLS["apac"] + "/file/simple/web"
    responses.get(url, json={"status": 0, "data_file_list": []})
    out = session.get("/file/simple/web")
    assert out["status"] == 0


@responses.activate
def test_get_sends_lowercase_bearer(session: PlaudSession) -> None:
    url = BASE_URLS["apac"] + "/whatever"
    responses.get(url, json={"status": 0})
    session.get("/whatever")
    sent = responses.calls[0].request
    # Lowercase "bearer " is what web.plaud.ai sends — keep it.
    assert sent.headers["Authorization"] == "bearer dummy-token"
    assert sent.headers["Origin"] == "https://web.plaud.ai"


@responses.activate
def test_404_maps_to_not_found(session: PlaudSession) -> None:
    url = BASE_URLS["apac"] + "/file/missing"
    responses.get(url, status=404)
    with pytest.raises(NotFoundError):
        session.get("/file/missing")


@responses.activate
def test_401_maps_to_authentication_error(session: PlaudSession) -> None:
    url = BASE_URLS["apac"] + "/some-endpoint"
    responses.get(url, status=401)
    with pytest.raises(AuthenticationError):
        session.get("/some-endpoint")


@responses.activate
def test_5xx_retries_then_raises(session: PlaudSession) -> None:
    url = BASE_URLS["apac"] + "/flaky"
    # All attempts (initial + retries) return 503
    for _ in range(4):
        responses.get(url, status=503)
    with pytest.raises(APIError):
        session.get("/flaky")


@responses.activate
def test_inband_region_redirect_updates_region(session: PlaudSession) -> None:
    url = BASE_URLS["apac"] + "/file/simple/web"
    responses.get(
        url,
        json={
            "status": -302,
            "data": {"domains": {"api": BASE_URLS["eu"]}},
        },
    )
    with pytest.raises(APIError):
        session.get("/file/simple/web")
    # Region should have been updated to match the server-suggested host.
    assert session.region == "eu"


@responses.activate
def test_get_raw_bytes_decompresses_gzip(session: PlaudSession) -> None:
    payload = b'[{"start_time":0,"content":"hello"}]'
    gz = gzip.compress(payload)
    responses.get("https://example.s3/transcript.json.gz", body=gz, status=200)
    out = session.get_raw_bytes("https://example.s3/transcript.json.gz")
    assert out == payload


@responses.activate
def test_get_raw_bytes_passes_plain_through(session: PlaudSession) -> None:
    responses.get("https://example.s3/plain.json", body=b'[{"a":1}]', status=200)
    out = session.get_raw_bytes("https://example.s3/plain.json")
    assert out == b'[{"a":1}]'


def test_unknown_region_rejected() -> None:
    with pytest.raises(ValueError):
        PlaudSession(token="x", region="mars")
