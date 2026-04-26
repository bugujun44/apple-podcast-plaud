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
