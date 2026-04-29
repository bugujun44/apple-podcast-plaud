"""HTTP session: browser-mimicking headers, retry, typed errors.

Plaud's reverse-engineered API rejects requests with default ``requests`` /
``urllib`` user agents (HTTP 403 with no body). The browser headers below
are the minimum viable set the live web app sends; trimming further has
been shown to trigger 403s in practice.

We send the bearer with a lowercase ``bearer`` token type — that's what the
official web app sends, and at least one server-side validator is case-
sensitive. Capitalised ``Bearer`` may also work but is not what we observe.
"""

from __future__ import annotations

import gzip
import io
import random
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from apple_podcast_plaud.plaud._endpoints import BASE_URLS
from apple_podcast_plaud.plaud.exceptions import (
    APIError,
    AuthenticationError,
    NotFoundError,
)

# Headers observed on web.plaud.ai when authenticated. The Sec-Fetch-* triplet
# and the Origin/Referer pair are required for some endpoints; app-platform /
# edit-from look custom but are present on every observed request.
_BROWSER_HEADERS: dict[str, str] = {
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Origin": "https://web.plaud.ai",
    "Referer": "https://web.plaud.ai/",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.6 Safari/605.1.15"
    ),
    "Sec-Fetch-Site": "same-site",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Dest": "empty",
    "app-platform": "web",
    "edit-from": "web",
}

REGION_REDIRECT_STATUS = -302  # in-band JSON status (NOT HTTP) used by Plaud
                                # to signal "wrong region — go to {data.domains.api}"


def _retry_adapter() -> HTTPAdapter:
    return HTTPAdapter(
        max_retries=Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[500, 502, 503, 504],
            allowed_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
        )
    )


class PlaudSession:
    """Minimal, region-aware HTTP wrapper around ``requests.Session``.

    Construct with a token and a starting region. If the server returns a
    -302 in-band redirect, ``region`` is updated automatically and the call
    is retried once.
    """

    def __init__(self, token: str, region: str = "us") -> None:
        if region not in BASE_URLS:
            raise ValueError(f"Unknown region {region!r}. Known: {sorted(BASE_URLS)}")
        self.token = token
        self.region = region
        self._sess = requests.Session()
        self._sess.headers.update(_BROWSER_HEADERS)
        # NB: lowercase "bearer" — matches what web.plaud.ai sends.
        self._sess.headers["Authorization"] = f"bearer {token}"
        self._sess.mount("https://", _retry_adapter())
        self._sess.mount("http://", _retry_adapter())

    @property
    def base_url(self) -> str:
        return BASE_URLS[self.region]

    def _full(self, path_or_url: str) -> str:
        if path_or_url.startswith("http://") or path_or_url.startswith("https://"):
            return path_or_url
        return self.base_url + path_or_url

    def get(self, path: str, *, params: dict | None = None, timeout: int = 30) -> dict:
        params = dict(params or {})
        params.setdefault("r", random.random())  # cache-buster the web app uses
        return self._do(lambda: self._sess.get(self._full(path), params=params, timeout=timeout))

    def post(self, path: str, *, json: Any = None, timeout: int = 30) -> dict:
        if isinstance(json, dict):
            json.setdefault("r", random.random())
        return self._do(lambda: self._sess.post(self._full(path), json=json, timeout=timeout))

    def patch(self, path: str, *, json: Any = None, timeout: int = 30) -> dict:
        if isinstance(json, dict):
            json.setdefault("r", random.random())
        return self._do(lambda: self._sess.patch(self._full(path), json=json, timeout=timeout))

    def _do(self, send) -> dict:
        """Run an HTTP call, mapping retry exhaustion into APIError."""
        try:
            return self._handle(send())
        except requests.exceptions.RetryError as e:
            raise APIError(f"Request failed after retries: {e}") from e
        except requests.exceptions.RequestException as e:
            raise APIError(f"Network error: {e}") from e

    def put_raw(
        self,
        url: str,
        *,
        data: Any = None,
        headers: dict[str, str] | None = None,
        timeout: int = 600,
    ) -> requests.Response:
        """PUT to a presigned URL — used for S3 multipart uploads.

        Bypasses our session entirely. The presigned URL already carries
        a signature in its query string; sending our session's
        ``Authorization: bearer …`` header alongside causes S3 to refuse
        with HTTP 400 "Only one auth mechanism allowed".
        """
        return requests.put(url, data=data, headers=headers, timeout=timeout)

    def get_raw_bytes(self, url: str, *, timeout: int = 60) -> bytes:
        """Fetch arbitrary URL (e.g. an S3 presigned link) and gunzip if needed.

        Plaud stores transcript JSONs gzip-compressed on S3 and serves them
        without ``Content-Encoding`` headers, so we sniff the magic bytes.
        """
        resp = self._sess.get(url, timeout=timeout)
        if resp.status_code >= 400:
            raise APIError(
                f"S3 fetch failed: {resp.status_code} {resp.text[:200]}",
                status_code=resp.status_code,
                response_body=resp.text,
            )
        body = resp.content
        if body[:2] == b"\x1f\x8b":
            body = gzip.GzipFile(fileobj=io.BytesIO(body)).read()
        return body

    def _handle(self, resp: requests.Response) -> dict:
        if resp.status_code == 401:
            raise AuthenticationError(
                "401 from Plaud. Token expired or invalid — refresh via "
                "web.plaud.ai → Console → copy(localStorage.getItem('tokenstr'))."
            )
        if resp.status_code == 404:
            raise NotFoundError(f"Not found: {resp.url}")
        if resp.status_code >= 400:
            raise APIError(
                f"HTTP {resp.status_code}: {resp.text[:300]}",
                status_code=resp.status_code,
                response_body=resp.text,
            )
        try:
            data = resp.json()
        except ValueError:
            raise APIError(f"Non-JSON response from {resp.url}: {resp.text[:200]}") from None

        # In-band region redirect — switch region and let the caller retry.
        if isinstance(data, dict) and data.get("status") == REGION_REDIRECT_STATUS:
            new_domain = (data.get("data") or {}).get("domains", {}).get("api", "")
            for region_key, base in BASE_URLS.items():
                if base == new_domain:
                    self.region = region_key
                    break
            raise APIError(
                "Plaud signalled region redirect; client retried region. "
                f"New region: {self.region}",
                status_code=REGION_REDIRECT_STATUS,
                response_body=resp.text,
            )

        return data
