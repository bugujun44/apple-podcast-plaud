"""Token resolution, password login, JWT region inference.

Token lookup priority:
    1. Explicit ``token`` parameter
    2. ``PLAUD_TOKEN`` environment variable
    3. ``.env`` file in current working directory
    4. ``~/.config/plaud/token`` file (XDG-style)

Two ways to get a token in the first place:

- ``login_with_password(email, password)`` — calls ``/auth/access-token`` and
  returns a fresh JWT. Use this if you registered Plaud with an email
  password.
- Copy ``localStorage.tokenstr`` from web.plaud.ai DevTools — required for
  Google-sign-in-only accounts that have no password set. See
  ``docs/token-extraction.md``.

Either way, persist via :func:`save_token` to ``~/.config/plaud/token``.
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any

import requests

from apple_podcast_plaud.plaud._endpoints import BASE_URLS, JWT_REGION_MAP
from apple_podcast_plaud.plaud.exceptions import APIError, AuthenticationError

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


# ---------------------------------------------------------------------------
# Password login (for accounts that have an email + password set)
# ---------------------------------------------------------------------------

# Headers good enough for the unauthenticated /auth/access-token endpoint;
# the protected endpoints in session.py use a richer header set.
_LOGIN_HEADERS: dict[str, str] = {
    "Content-Type": "application/x-www-form-urlencoded",
    "Accept": "*/*",
    "Origin": "https://web.plaud.ai",
    "Referer": "https://web.plaud.ai/",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.6 Safari/605.1.15"
    ),
    "app-platform": "web",
}


def login_with_password(
    email: str,
    password: str,
    *,
    region: str = "us",
    timeout: int = 30,
) -> str:
    """Exchange an email/password for a fresh bearer token.

    Will not work for accounts that registered via Google/Apple sign-in
    only — those have no password set on the Plaud side. Such users must
    set a password first via the "Forgot password" flow at web.plaud.ai
    or extract a token from localStorage instead.

    Args:
        email: Plaud account email.
        password: Plaud account password.
        region: Initial region to attempt. ``us`` works for accounts in any
            region in practice — the server returns the right token regardless
            and ``infer_region`` against the resulting JWT tells you the
            account's actual home region. Pass a known region only if you
            already know it (e.g. ``apac``).
        timeout: Request timeout in seconds.

    Returns:
        The bearer access token (no ``"bearer "`` prefix).

    Raises:
        AuthenticationError: if the credentials are rejected.
        APIError: on transport / non-auth API errors.
    """
    if region not in BASE_URLS:
        raise ValueError(f"Unknown region {region!r}. Known: {sorted(BASE_URLS)}")
    url = BASE_URLS[region] + "/auth/access-token"
    body = {"username": email, "password": password}
    try:
        resp = requests.post(url, data=body, headers=_LOGIN_HEADERS, timeout=timeout)
    except requests.exceptions.RequestException as e:
        raise APIError(f"Network error during login: {e}") from e

    if resp.status_code == 401:
        raise AuthenticationError("Plaud rejected the password (401).")
    if resp.status_code >= 400:
        raise APIError(
            f"Login HTTP {resp.status_code}: {resp.text[:300]}",
            status_code=resp.status_code,
            response_body=resp.text,
        )

    try:
        data: dict[str, Any] = resp.json()
    except ValueError as e:
        raise APIError(f"Login returned non-JSON: {resp.text[:200]}") from e

    # Plaud's body either uses ``status`` or HTTP semantics — both observed.
    status = data.get("status")
    if status not in (None, 0):
        msg = data.get("msg") or "wrong account or password"
        # Common server message for bad creds — surface as AuthenticationError.
        if "wrong" in msg.lower() or "password" in msg.lower():
            raise AuthenticationError(f"Plaud login failed: {msg}")
        raise APIError(f"Plaud login failed (status={status}): {msg}")

    token = data.get("access_token") or (data.get("data") or {}).get("access_token")
    if not token:
        raise APIError(f"Login response had no access_token: {resp.text[:300]}")
    return token


# ---------------------------------------------------------------------------
# Persist token (and credentials) to disk
# ---------------------------------------------------------------------------


def save_token(token: str, *, token_file: Path = DEFAULT_TOKEN_FILE) -> Path:
    """Write the token to disk with mode 0600 (readable only by owner).

    Returns the absolute path. Creates the parent directory if missing.
    """
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text(token.strip() + "\n")
    token_file.chmod(0o600)
    try:
        token_file.parent.chmod(0o700)
    except PermissionError:  # pragma: no cover
        pass
    return token_file


# ---------------------------------------------------------------------------
# Token introspection (for ``apb auth status`` and pre-flight checks)
# ---------------------------------------------------------------------------


def token_info(token: str) -> dict[str, Any]:
    """Decode the JWT and return a small dict with the fields users care about.

    All values are derived locally from the token without contacting Plaud,
    so this is fast and works offline. Use :func:`verify_token` if you also
    want to confirm the server still accepts the token.

    Returns:
        ``{"region": str, "issued_at": int, "expires_at": int,
            "expires_in_days": int, "user_id": str | None}``

        Times are unix-epoch seconds; ``expires_in_days`` may be negative
        for already-expired tokens.
    """
    import time

    payload = decode_jwt_payload(token)
    iat = int(payload.get("iat") or 0)
    exp = int(payload.get("exp") or 0)
    return {
        "region": infer_region(token),
        "issued_at": iat,
        "expires_at": exp,
        "expires_in_days": (exp - int(time.time())) // 86400 if exp else 0,
        "user_id": payload.get("sub"),
    }


def verify_token(token: str, *, region: str | None = None, timeout: int = 15) -> bool:
    """Hit a cheap, side-effect-free endpoint to confirm the server accepts the token.

    Returns True on 2xx, False on 401. Anything else is re-raised so the caller
    can distinguish "your token is bad" from "the network is bad".

    Args:
        token: Bearer token to test.
        region: BASE_URLS key. Defaults to JWT-inferred region.
        timeout: Request timeout in seconds.
    """
    region = region or infer_region(token)
    if region not in BASE_URLS:
        raise ValueError(f"Unknown region {region!r}")
    url = BASE_URLS[region] + "/file/simple/web"
    headers = dict(_LOGIN_HEADERS)
    headers["Authorization"] = f"bearer {token}"
    try:
        resp = requests.get(url, headers=headers, params={"limit": 1}, timeout=timeout)
    except requests.exceptions.RequestException as e:
        raise APIError(f"Network error during verify: {e}") from e
    if resp.status_code == 401:
        return False
    if resp.status_code >= 400:
        raise APIError(
            f"Verify HTTP {resp.status_code}: {resp.text[:300]}",
            status_code=resp.status_code,
            response_body=resp.text,
        )
    return True
