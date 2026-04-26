"""Read Apple Podcasts' local SQLite to find downloaded episodes.

Apple Podcasts on macOS keeps a Core Data SQLite database at
``~/Library/Group Containers/243LU875E5.groups.com.apple.podcasts/Documents/MTLibrary.sqlite``,
and stores downloaded audio under the sibling ``Library/Cache/`` directory
with random-UUID filenames. The mapping podcast title ⇄ episode title ⇄
on-disk path lives in ``ZMTPODCAST`` and ``ZMTEPISODE``.

Timestamps are Core Data style — seconds since 2001-01-01 UTC, so we
add 978307200 to convert to the unix epoch.

We open the database read-only and pick up the WAL transparently. We
never write here — Apple's app keeps the file open.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote

DEFAULT_DB = (
    Path.home()
    / "Library"
    / "Group Containers"
    / "243LU875E5.groups.com.apple.podcasts"
    / "Documents"
    / "MTLibrary.sqlite"
)

CORE_DATA_EPOCH_OFFSET = 978_307_200  # seconds between 2001-01-01 and 1970-01-01


@dataclass
class Episode:
    """One Apple Podcasts episode row, narrowed to what we need."""

    podcast_title: str
    episode_title: str
    m4a_path: Path
    import_date_unix: int  # seconds since unix epoch


def _open_db(db_path: Path = DEFAULT_DB) -> sqlite3.Connection:
    if not db_path.exists():
        raise FileNotFoundError(
            f"Apple Podcasts SQLite not found at {db_path}. "
            f"Open Podcasts.app at least once on this Mac."
        )
    # ``mode=ro`` + URI lets us coexist with the running app (which holds a
    # write lock). The WAL is auto-followed.
    uri = f"file:{db_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _row_to_episode(row: sqlite3.Row) -> Episode | None:
    asset_url = row["asset_url"]
    if not asset_url or not asset_url.startswith("file://"):
        return None
    path = Path(unquote(asset_url[len("file://") :]))
    if not path.exists():
        return None
    return Episode(
        podcast_title=row["podcast_title"] or "",
        episode_title=row["episode_title"] or "",
        m4a_path=path,
        import_date_unix=int((row["import_date"] or 0) + CORE_DATA_EPOCH_OFFSET),
    )


_BASE_QUERY = """
SELECT
    p.ZTITLE                                AS podcast_title,
    COALESCE(e.ZCLEANEDTITLE, e.ZTITLE)     AS episode_title,
    e.ZASSETURL                             AS asset_url,
    e.ZIMPORTDATE                           AS import_date
FROM ZMTEPISODE e
LEFT JOIN ZMTPODCAST p ON e.ZPODCASTUUID = p.ZUUID
WHERE e.ZASSETURL LIKE 'file://%'
"""


def list_downloaded(
    *,
    limit: int = 20,
    db_path: Path = DEFAULT_DB,
) -> list[Episode]:
    """Return downloaded episodes whose m4a still exists on disk, newest first."""
    sql = _BASE_QUERY + " ORDER BY e.ZIMPORTDATE DESC LIMIT ?"
    out: list[Episode] = []
    with _open_db(db_path) as conn:
        for row in conn.execute(sql, (limit,)):
            ep = _row_to_episode(row)
            if ep is not None:
                out.append(ep)
    return out


def find_by_keyword(
    keyword: str,
    *,
    db_path: Path = DEFAULT_DB,
    limit: int = 50,
) -> list[Episode]:
    """Case-insensitive substring match against podcast OR episode title.

    The newest match comes first. Caller decides whether to use the top hit
    automatically or prompt the user.
    """
    if not keyword:
        return []
    pat = f"%{keyword}%"
    sql = (
        _BASE_QUERY
        + """
        AND (
            p.ZTITLE LIKE ? OR
            COALESCE(e.ZCLEANEDTITLE, e.ZTITLE) LIKE ?
        )
        ORDER BY e.ZIMPORTDATE DESC LIMIT ?
        """
    )
    out: list[Episode] = []
    with _open_db(db_path) as conn:
        for row in conn.execute(sql, (pat, pat, limit)):
            ep = _row_to_episode(row)
            if ep is not None:
                out.append(ep)
    return out
