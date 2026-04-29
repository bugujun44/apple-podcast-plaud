# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- Initial project skeleton: package layout, license, README, pyproject.
- `apple_podcast_plaud.plaud` subpackage:
  - Region-aware base URL routing (`us` / `eu` / `apac`) keyed on the JWT
    `region` claim. Auto-detect via `infer_region`.
  - Token resolution chain: explicit param → `PLAUD_TOKEN` → `.env` →
    `~/.config/plaud/token`.
  - Browser-mimicking HTTP session with retry, gzip decompression of S3
    bodies, and in-band -302 region-redirect handling.
  - Typed exceptions: `PlaudError`, `AuthenticationError`, `NotFoundError`,
    `APIError`, `UploadError`, `AnalysisTimeoutError`.
- Tests for `auth` and `session` (no real network).
- `auth.login_with_password()` for accounts that have a password set; the
  server message ``wrong account or password`` is mapped to
  ``AuthenticationError`` even when returned with HTTP 200.
- `auth.save_token()` writes ``~/.config/plaud/token`` with mode 0600.
- `auth.token_info()` decodes the JWT locally and returns
  ``region`` / ``issued_at`` / ``expires_at`` / ``expires_in_days`` /
  ``user_id``. No network call.
- `auth.verify_token()` does a cheap ``/file/simple/web`` GET to confirm
  the server still accepts the token (returns ``True`` / ``False`` for
  401, raises for other transport errors).
- `bridge.apple_podcasts` (read-only Apple Podcasts SQLite query),
  `bridge.language` (CJK script detection), `bridge.output`
  (transcript.md + summary.md + metadata.json + JSON envelope writer),
  `bridge.tracks.plaud_track` (upload → wait → fetch orchestrator),
  `bridge.cli` (``apb`` click app: ``auth login`` / ``set-token`` /
  ``status`` / ``logout``, ``list-podcasts``, ``transcribe``).
- ``scripts/dev-install.sh``: idempotent dev environment bootstrap that
  works around a Python 3.14 ``.pth`` honouring bug on some Macs by
  writing both a plain ``.pth`` and a ``PYTHONPATH`` export.

### Changed
- Build backend: hatchling → setuptools. Hatchling's editable install
  generated an entry-point script that couldn't import the package on
  some Python 3.14 builds.
