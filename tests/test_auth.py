"""Tests for token resolution and JWT region inference."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from apple_podcast_plaud.plaud.auth import (
    decode_jwt_payload,
    infer_region,
    resolve_token,
)
from apple_podcast_plaud.plaud.exceptions import AuthenticationError


def _fake_jwt(payload: dict) -> str:
    """Build a JWT string with the requested payload (signature is junk)."""

    def b64(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

    header = b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    body = b64(json.dumps(payload).encode())
    sig = b64(b"signature-not-checked")
    return f"{header}.{body}.{sig}"


# ---------------------------------------------------------------------------
# resolve_token priority chain
# ---------------------------------------------------------------------------


def test_resolve_token_explicit_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PLAUD_TOKEN", "from-env")
    assert resolve_token("explicit") == "explicit"


def test_resolve_token_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PLAUD_TOKEN", "env-value")
    assert resolve_token() == "env-value"


def test_resolve_token_strips_bearer_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PLAUD_TOKEN", "bearer my-token")
    assert resolve_token() == "my-token"
    monkeypatch.setenv("PLAUD_TOKEN", "Bearer  my-token  ")
    assert resolve_token() == "my-token"


def test_resolve_token_file_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PLAUD_TOKEN", raising=False)
    token_file = tmp_path / "token"
    token_file.write_text("from-file\n")
    assert resolve_token(token_file=token_file) == "from-file"


def test_resolve_token_raises_when_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PLAUD_TOKEN", raising=False)
    monkeypatch.chdir(tmp_path)  # avoid picking up a real .env
    with pytest.raises(AuthenticationError):
        resolve_token(token_file=tmp_path / "missing")


# ---------------------------------------------------------------------------
# JWT payload decoding & region inference
# ---------------------------------------------------------------------------


def test_decode_jwt_payload_roundtrip() -> None:
    token = _fake_jwt({"sub": "user-1", "region": "aws:ap-northeast-1", "exp": 123})
    payload = decode_jwt_payload(token)
    assert payload["region"] == "aws:ap-northeast-1"
    assert payload["sub"] == "user-1"


def test_decode_jwt_payload_rejects_non_jwt() -> None:
    with pytest.raises(AuthenticationError):
        decode_jwt_payload("not-a-jwt")


@pytest.mark.parametrize(
    ("claim", "expected"),
    [
        ("aws:ap-northeast-1", "apac"),
        ("aws:eu-central-1", "eu"),
        ("aws:us-east-1", "us"),
        ("aws:us-west-2", "us"),
    ],
)
def test_infer_region_from_jwt_claim(claim: str, expected: str) -> None:
    token = _fake_jwt({"region": claim})
    assert infer_region(token) == expected


def test_infer_region_falls_back_when_claim_unknown() -> None:
    token = _fake_jwt({"region": "aws:sa-east-1"})
    assert infer_region(token, default="eu") == "eu"


def test_infer_region_falls_back_for_garbage_token() -> None:
    assert infer_region("not-a-jwt", default="us") == "us"
