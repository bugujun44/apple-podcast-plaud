"""Per-region API base URLs and path constants.

Plaud's web app shards user data across AWS regions; the API host you must
hit depends on where the account was created. The region of the current
token can be read from the JWT ``region`` claim (e.g. ``aws:ap-northeast-1``).

The reverse-engineered TS toolkit only ships ``us`` / ``eu`` and lets the
server respond with a -302 indicating "wrong host"; this client adds
``apac`` (Tokyo) and a JWT-based auto-detect so APAC users don't need to
patch the source.
"""

from __future__ import annotations

BASE_URLS: dict[str, str] = {
    "us": "https://api.plaud.ai",
    "eu": "https://api-euc1.plaud.ai",
    "apac": "https://api-apne1.plaud.ai",
}

# Map JWT ``region`` claim values to BASE_URLS keys.
JWT_REGION_MAP: dict[str, str] = {
    "aws:us-east-1": "us",
    "aws:us-west-2": "us",
    "aws:eu-central-1": "eu",
    "aws:ap-northeast-1": "apac",
}


def path(base: str, suffix: str) -> str:
    """Compose a full URL given a region base and a path suffix."""
    return f"{base}{suffix}"


# ---------------------------------------------------------------------------
# Path suffixes (combined with BASE_URLS[region] at request time).
# ---------------------------------------------------------------------------

# Files / Recordings
P_FILE_SIMPLE = "/file/simple/web"
P_FILE_LIST = "/file/list"
P_FILE_DETAIL = "/file"  # {base}/file/{id}
P_FILE_UPLOAD_URL = "/file/get_upload_presigned_url"
P_FILE_MERGE = "/file/merge_multipart"
P_FILE_CONFIRM = "/file/confirm_upload"
P_FILE_TEMP_URL = "/file/temp-url"  # {base}/file/temp-url/{id}

# AI / Analysis
P_AI_TRANSSUMM = "/ai/transsumm"  # {base}/ai/transsumm/{id}

# Tags / Speakers
P_FILETAG = "/filetag/"
P_SPEAKER_LIST = "/speaker/list"
P_SPEAKER_SYNC = "/speaker/sync"
