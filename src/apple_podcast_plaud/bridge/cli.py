"""``apb`` — Apple-Podcast-bridge command-line entry point.

Two top-level command groups:

- ``apb auth``        — login (Path A), set-token (Path B), status, logout.
- ``apb transcribe``  — locate an Apple Podcasts download by keyword, ship to
                        Plaud, write a transcript, emit JSON envelope.

Plus utilities:

- ``apb list-podcasts`` — print recently downloaded episodes.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path

import click

from apple_podcast_plaud.bridge import apple_podcasts as ap
from apple_podcast_plaud.bridge import language as lang
from apple_podcast_plaud.bridge.output import (
    DEFAULT_ROOT,
    write_artifacts,
)
from apple_podcast_plaud.bridge.tracks.plaud_track import transcribe_via_plaud
from apple_podcast_plaud.plaud import (
    PlaudClient,
    login_with_password,
    save_token,
    token_info,
    verify_token,
)
from apple_podcast_plaud.plaud.auth import DEFAULT_TOKEN_FILE
from apple_podcast_plaud.plaud.exceptions import (
    AuthenticationError,
    PlaudError,
)


@click.group()
@click.version_option(package_name="apple-podcast-plaud", prog_name="apb")
def main() -> None:
    """Apple Podcasts → Plaud → text bridge."""


# ---------------------------------------------------------------------------
# auth
# ---------------------------------------------------------------------------


@main.group()
def auth() -> None:
    """Manage your Plaud credentials."""


@auth.command("login")
@click.option("--email", prompt=True, help="Plaud account email.")
@click.password_option(confirmation_prompt=False, help="Plaud account password.")
@click.option(
    "--region",
    default="us",
    show_default=True,
    type=click.Choice(["us", "eu", "apac"]),
    help="Region to attempt first; the resolved token's region is used afterwards.",
)
def auth_login(email: str, password: str, region: str) -> None:
    """Path A — exchange email + password for a fresh token (if your account has one).

    Some Plaud accounts (Google sign-in only) cannot use this; if you see
    'wrong account or password' even with the right credentials, switch to
    'apb auth set-token' instead.
    """
    try:
        token = login_with_password(email, password, region=region)
    except AuthenticationError as e:
        raise click.ClickException(
            f"{e}\n\nIf this account uses Google/Apple sign-in only, "
            "you have no password to enter. Use 'apb auth set-token' instead."
        ) from e
    path = save_token(token)
    click.echo(f"Saved token → {path}")
    _print_status(token)


@auth.command("set-token")
@click.option(
    "--from-stdin/--no-from-stdin",
    default=True,
    help="Read the token from stdin (default). Disable to be prompted interactively.",
)
def auth_set_token(from_stdin: bool) -> None:
    """Path B — paste a token grabbed from web.plaud.ai's localStorage.

    On the web app, open DevTools → Console and run:

        copy(localStorage.getItem('tokenstr'))

    Then run this command and paste; finish with Ctrl-D (or just press Enter
    once if you used --no-from-stdin).
    """
    if from_stdin:
        click.echo("Paste your Plaud token, then press Enter and Ctrl-D:", err=True)
        raw = sys.stdin.read()
    else:
        raw = click.prompt("Token", hide_input=True)
    # Be forgiving — strip whitespace, optional 'bearer ' prefix, stray
    # angle brackets that shells sometimes leave behind.
    cleaned = "".join(raw.split())
    if cleaned.startswith("<") and cleaned.endswith(">"):
        cleaned = cleaned[1:-1]
    if cleaned.lower().startswith("bearer"):
        cleaned = cleaned[6:]
    if not cleaned:
        raise click.ClickException("Empty token.")
    if cleaned.count(".") != 2:
        raise click.ClickException(
            f"That doesn't look like a JWT (need 2 dots, got {cleaned.count('.')}). "
            "Did you accidentally copy a wrapped value?"
        )
    path = save_token(cleaned)
    click.echo(f"Saved token → {path}")
    _print_status(cleaned)


@auth.command("status")
def auth_status() -> None:
    """Show region + expiry for the saved token, then ping Plaud to confirm."""
    if not DEFAULT_TOKEN_FILE.exists():
        raise click.ClickException(
            f"No token at {DEFAULT_TOKEN_FILE}. "
            "Run 'apb auth login' or 'apb auth set-token'."
        )
    token = DEFAULT_TOKEN_FILE.read_text().strip()
    _print_status(token)


@auth.command("logout")
def auth_logout() -> None:
    """Delete the saved token (does NOT revoke it server-side)."""
    if DEFAULT_TOKEN_FILE.exists():
        DEFAULT_TOKEN_FILE.unlink()
        click.echo(f"Deleted {DEFAULT_TOKEN_FILE}.")
    else:
        click.echo(f"No token at {DEFAULT_TOKEN_FILE}; nothing to do.")


def _print_status(token: str) -> None:
    info = token_info(token)
    when = (
        datetime.fromtimestamp(info["expires_at"]).strftime("%Y-%m-%d %H:%M")
        if info["expires_at"]
        else "(unknown)"
    )
    click.echo(f"  region:        {info['region']}")
    click.echo(f"  user_id:       {info['user_id']}")
    click.echo(f"  expires:       {when}  (in {info['expires_in_days']} days)")
    click.echo("  server check:  ", nl=False)
    try:
        ok = verify_token(token, region=info["region"])
    except PlaudError as e:
        click.echo(f"network error — {e}")
        return
    click.echo("ok" if ok else "REJECTED — token is invalid; rotate it.")


# ---------------------------------------------------------------------------
# list-podcasts
# ---------------------------------------------------------------------------


@main.command("list-podcasts")
@click.option("-n", "--limit", default=10, show_default=True, type=int)
@click.option(
    "--json", "as_json", is_flag=True, help="Output JSON instead of a table."
)
def list_podcasts(limit: int, as_json: bool) -> None:
    """List recently downloaded Apple Podcasts episodes."""
    eps = ap.list_downloaded(limit=limit)
    if as_json:
        click.echo(
            json.dumps(
                [
                    {
                        "podcast": e.podcast_title,
                        "episode": e.episode_title,
                        "m4a_path": str(e.m4a_path),
                        "import_date_unix": e.import_date_unix,
                    }
                    for e in eps
                ],
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    if not eps:
        click.echo("No downloaded episodes found.", err=True)
        return
    for i, e in enumerate(eps, 1):
        when = datetime.fromtimestamp(e.import_date_unix).strftime("%Y-%m-%d %H:%M")
        click.echo(f"[{i}] {when}  {e.podcast_title}  ·  {e.episode_title}")


# ---------------------------------------------------------------------------
# transcribe
# ---------------------------------------------------------------------------


@main.command("transcribe")
@click.argument("keyword")
@click.option(
    "--out-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help=f"Output directory. Default: {DEFAULT_ROOT}/<date>-<slug>/",
)
@click.option(
    "--language",
    default=None,
    help="Override language detection (e.g. zh / en / ja). "
    "If omitted, auto-detected from podcast / episode titles.",
)
@click.option(
    "--json-out",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Write the JSON envelope to this path. Use '-' for stdout (default).",
)
@click.option(
    "--timeout",
    default=1200,
    show_default=True,
    type=int,
    help="Max seconds to wait for Plaud analysis.",
)
@click.option(
    "--quiet",
    is_flag=True,
    help="Suppress progress text. JSON envelope is always emitted.",
)
def transcribe(
    keyword: str,
    out_dir: Path | None,
    language: str | None,
    json_out: Path | None,
    timeout: int,
    quiet: bool,
) -> None:
    """Transcribe a downloaded episode whose title matches KEYWORD."""

    def progress(msg: str) -> None:
        if not quiet:
            click.echo(msg, err=True)

    matches = ap.find_by_keyword(keyword, limit=20)
    if not matches:
        raise click.ClickException(
            f"No downloaded Apple Podcasts episode matches {keyword!r}. "
            "Run 'apb list-podcasts' to see what's available."
        )
    if len(matches) > 1:
        progress(
            f"{len(matches)} matches — picking the most recent one. "
            "Pass a more specific keyword to disambiguate."
        )
    ep = matches[0]
    progress(
        f"→ Selected: {ep.podcast_title} · {ep.episode_title} "
        f"({ep.m4a_path.name}, {ep.m4a_path.stat().st_size // 1024} KB)"
    )

    detected = lang.detect(ep.podcast_title, ep.episode_title)
    final_lang = language or detected
    progress(f"→ Language: {final_lang} (detected: {detected})")

    client = PlaudClient()
    progress(f"→ PlaudClient region={client.region}")

    started = time.monotonic()
    result = transcribe_via_plaud(
        client,
        ep.m4a_path,
        podcast_title=ep.podcast_title,
        episode_title=ep.episode_title,
        language=final_lang,
        timeout=timeout,
        progress=progress,
    )

    envelope = write_artifacts(
        result,
        out_dir=out_dir,
        elapsed_sec=int(time.monotonic() - started),
    )

    payload = json.dumps(envelope, ensure_ascii=False, indent=2)
    if json_out is None or str(json_out) == "-":
        click.echo(payload)
    else:
        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(payload, encoding="utf-8")
        progress(f"→ Wrote JSON envelope: {json_out}")


if __name__ == "__main__":  # pragma: no cover
    main()
