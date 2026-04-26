"""Tests for password login + token persistence."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest
import responses

from apple_podcast_plaud.plaud._endpoints import BASE_URLS
from apple_podcast_plaud.plaud.auth import login_with_password, save_token
from apple_podcast_plaud.plaud.exceptions import APIError, AuthenticationError


@responses.activate
def test_login_returns_access_token() -> None:
    responses.post(
        BASE_URLS["us"] + "/auth/access-token",
        json={"access_token": "tok-123", "token_type": "bearer"},
    )
    token = login_with_password("user@example.com", "secret")
    assert token == "tok-123"

    sent = responses.calls[0].request
    assert sent.headers["Content-Type"] == "application/x-www-form-urlencoded"
    # Form body — not JSON. ``responses`` exposes it as a str.
    body = sent.body if isinstance(sent.body, str) else sent.body.decode()
    assert "username=user%40example.com" in body
    assert "password=secret" in body


@responses.activate
def test_login_works_against_apac_endpoint() -> None:
    responses.post(
        BASE_URLS["apac"] + "/auth/access-token",
        json={"access_token": "tok-apac"},
    )
    token = login_with_password("user@example.com", "secret", region="apac")
    assert token == "tok-apac"


@responses.activate
def test_login_handles_data_wrapper() -> None:
    """Server sometimes wraps the token in a ``data`` envelope — accept both."""
    responses.post(
        BASE_URLS["us"] + "/auth/access-token",
        json={"status": 0, "data": {"access_token": "tok-wrapped"}},
    )
    assert login_with_password("u@e.com", "p") == "tok-wrapped"


@responses.activate
def test_login_401_raises_authentication_error() -> None:
    responses.post(BASE_URLS["us"] + "/auth/access-token", status=401)
    with pytest.raises(AuthenticationError):
        login_with_password("u@e.com", "wrong")


@responses.activate
def test_login_wrong_account_message_is_auth_error() -> None:
    """Plaud sometimes returns 200 OK with status=-1 + 'wrong account or password'."""
    responses.post(
        BASE_URLS["us"] + "/auth/access-token",
        json={"status": -1, "msg": "wrong account or password"},
    )
    with pytest.raises(AuthenticationError):
        login_with_password("u@e.com", "wrong")


@responses.activate
def test_login_other_status_is_api_error() -> None:
    responses.post(
        BASE_URLS["us"] + "/auth/access-token",
        json={"status": -42, "msg": "rate limited or whatever"},
    )
    with pytest.raises(APIError):
        login_with_password("u@e.com", "p")


def test_login_unknown_region_rejected() -> None:
    with pytest.raises(ValueError):
        login_with_password("u@e.com", "p", region="mars")


# ---------------------------------------------------------------------------
# save_token
# ---------------------------------------------------------------------------


def test_save_token_writes_with_0600(tmp_path: Path) -> None:
    target = tmp_path / "subdir" / "token"
    out = save_token("my-token  ", token_file=target)
    assert out == target
    assert target.read_text().strip() == "my-token"
    mode = stat.S_IMODE(os.stat(target).st_mode)
    assert mode == 0o600


# ---------------------------------------------------------------------------
# verify_token / token_info
# ---------------------------------------------------------------------------

import base64
import json
import time

import responses as resp_lib  # noqa: E402

from apple_podcast_plaud.plaud.auth import token_info, verify_token  # noqa: E402


def _fake_jwt(payload: dict) -> str:
    def b64(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

    h = b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    p = b64(json.dumps(payload).encode())
    s = b64(b"sig")
    return f"{h}.{p}.{s}"


def test_token_info_extracts_fields() -> None:
    now = int(time.time())
    token = _fake_jwt({
        "sub": "user-1",
        "region": "aws:ap-northeast-1",
        "iat": now,
        "exp": now + 30 * 86400,
    })
    info = token_info(token)
    assert info["region"] == "apac"
    assert info["user_id"] == "user-1"
    assert 29 <= info["expires_in_days"] <= 30


@resp_lib.activate
def test_verify_token_returns_true_on_2xx() -> None:
    token = _fake_jwt({"region": "aws:ap-northeast-1"})
    resp_lib.get(BASE_URLS["apac"] + "/file/simple/web", json={"status": 0})
    assert verify_token(token) is True


@resp_lib.activate
def test_verify_token_returns_false_on_401() -> None:
    token = _fake_jwt({"region": "aws:us-east-1"})
    resp_lib.get(BASE_URLS["us"] + "/file/simple/web", status=401)
    assert verify_token(token) is False


@resp_lib.activate
def test_verify_token_raises_on_5xx() -> None:
    token = _fake_jwt({"region": "aws:us-east-1"})
    resp_lib.get(BASE_URLS["us"] + "/file/simple/web", status=503)
    with pytest.raises(APIError):
        verify_token(token)
