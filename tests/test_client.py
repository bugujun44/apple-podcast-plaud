"""Smoke tests for the top-level :class:`PlaudClient`."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from apple_podcast_plaud.plaud.client import PlaudClient


def _fake_jwt(payload: dict) -> str:
    def b64(b: bytes) -> str:
        return base64.urlsafe_b64encode(b).rstrip(b"=").decode()

    return ".".join(
        [
            b64(json.dumps({"alg": "HS256"}).encode()),
            b64(json.dumps(payload).encode()),
            b64(b"sig"),
        ]
    )


def test_client_picks_up_explicit_token() -> None:
    token = _fake_jwt({"region": "aws:ap-northeast-1"})
    client = PlaudClient(token=token)
    assert client.token == token
    assert client.region == "apac"
    assert client.session.region == "apac"
    assert client.recordings is not None
    assert client.transcriptions is not None


def test_client_explicit_region_wins() -> None:
    token = _fake_jwt({"region": "aws:ap-northeast-1"})
    client = PlaudClient(token=token, region="us")
    assert client.region == "us"


def test_client_falls_back_to_us_when_jwt_lacks_region() -> None:
    token = _fake_jwt({"sub": "x"})
    client = PlaudClient(token=token)
    assert client.region == "us"


def test_client_resolves_token_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """When constructed without an explicit token, fall through to env var."""
    token = _fake_jwt({"region": "aws:eu-central-1"})
    monkeypatch.setenv("PLAUD_TOKEN", token)
    client = PlaudClient()
    assert client.token == token
    assert client.region == "eu"
