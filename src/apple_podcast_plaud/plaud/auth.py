"""Token resolution + JWT region inference.

Token lookup priority:
    1. Explicit ``token`` parameter
    2. ``PLAUD_TOKEN`` environment variable
    3. ``.env`` file in current working directory
    4. ``~/.config/plaud/token`` file (XDG-style)

We deliberately do not implement email/password login. Plaud's first-party
login flow is OAuth-only for many users (Google sign-in), and burning
credentials in a CLI tool that has been reverse-engineered is bad hygiene.
Users grab a bearer token from the web app's localStorage; see
``docs/token-extraction.md``.
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path

from apple_podcast_plaud.plaud._endpoints import JWT_REGION_MAP
from apple_podcast_plaud.plaud.exceptions import AuthenticationError

DEFAULT_TOKEN_DIR = Path.home() / ".config" / "plaud"
DEFAULT_TOKEN_FILE = DEFAULT_TOKEN_DIR / "token"
DOTENV_FILE = Path(".env")
ENV_VAR = "PLAUD_TOKEN"


def _read_dotenv_token(path: Path = DOTENV_FILE) -> str | None:
    """Read ``PLAUD_TOKEN`` from a ``.env`` file in the current directory.

    No external dependency — we only support the simplest ``KEY=VALUE``
    form. Lines beginning with ``#`` and lines without ``=`` are skipped.
    """
    if not path.exists():
        return None
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key.strip() == ENV_VAR:
            value = value.strip().strip("\"'")
            if value:
                return value
    return None


def resolve_token(
    token: str | None = None,
    *,
    token_file: Path = DEFAULT_TOKEN_FILE,
) -> str:
    """Resolve the Plaud bearer token from the priority chain above.

    Args:
        token: Explicit override. Wins if non-empty.
        token_file: Override the on-disk fallback location (mostly for tests).

    Returns:
        The resolved token, with ``"bearer "`` / ``"Bearer "`` prefix and
        surrounding whitespace stripped.

    Raises:
        AuthenticationError: if no token can be found in any location.
    """
    candidates: list[str | None] = [
        token,
        os.environ.get(ENV_VAR),
        _read_dotenv_token(),
        token_file.read_text().strip() if token_file.exists() else None,
    ]
    for cand in candidates:
        if not cand:
            continue
        cleaned = cand.strip()
        if cleaned.lower().startswith("bearer "):
            cleaned = cleaned[7:].strip()
        if cleaned:
            return cleaned
    raise AuthenticationError(
        "No Plaud token found. Set PLAUD_TOKEN, drop one in ~/.config/plaud/token, "
        "or pass token=... explicitly. See docs/token-extraction.md."
    )


def _b64url_decode(segment: str) -> bytes:
    """Decode a base64url segment (JWT-flavoured) — pads as needed."""
    pad = (-len(segment)) % 4
    return base64.urlsafe_b64decode(segment + ("=" * pad))


def decode_jwt_payload(token: str) -> dict:
    """Decode the JWT payload (middle segment) without verifying the signature.

    We never trust the contents for auth — the server validates the signature.
    We only inspect ``region`` and ``exp`` for client-side routing/UX.
    """
    parts = token.split(".")
    if len(parts) != 3:
        raise AuthenticationError("Token does not look like a JWT (need 3 dot-separated segments).")
    try:
        return json.loads(_b64url_decode(parts[1]))
    except (ValueError, json.JSONDecodeError) as e:
        raise AuthenticationError(f"Failed to decode JWT payload: {e}") from e


def infer_region(token: str, *, default: str = "us") -> str:
    """Return the BASE_URLS key best matching the token's home region.

    Falls back to ``default`` if the JWT carries an unknown region claim
    or no claim at all (older tokens).
    """
    try:
        payload = decode_jwt_payload(token)
    except AuthenticationError:
        return default
    raw_region = payload.get("region")
    if isinstance(raw_region, str) and raw_region in JWT_REGION_MAP:
        return JWT_REGION_MAP[raw_region]
    return default
