# apple-podcast-plaud

> Apple Podcasts → Plaud → text. Detect a downloaded episode, auto‑upload to Plaud, wait for transcription, hand the transcript back to any coding agent.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![Status: Alpha](https://img.shields.io/badge/status-alpha-orange)](#)

## What it does

You download a podcast episode in Apple Podcasts on your Mac. Then you ask
your coding agent ("Claude Code", "Cursor", "Cline", or anything else) to
transcribe it. The skill / CLI:

1. Locates the downloaded `m4a` from the Apple Podcasts SQLite + cache
2. Auto-uploads it to your [Plaud](https://www.plaud.ai) account (Pro
   subscription required — uses your existing minute quota; the package itself
   has no transcription cost)
3. Polls until Plaud finishes transcription + AI summary
4. Writes a verbatim transcript Markdown, an AI summary Markdown, and a
   metadata JSON to a known location
5. Prints a JSON envelope to stdout — your agent picks it up and decides what
   to do next (write an article, ingest into a knowledge base, search, …)

For **English** podcasts that have a native Apple-generated transcript, the
package can skip Plaud entirely and use the free Apple TTML cache instead
(no quota burn, instant). See [docs/language-routing.md](docs/language-routing.md).

## Why

- Apple Podcasts does not generate native transcripts for Chinese (and many
  other) podcasts. Plaud Pro is great at Chinese ASR and offers AI summaries.
- Existing Plaud reverse-engineered tools (TypeScript, Python) don't fit a
  clean Apple-Podcasts-anchored agent workflow:
  - sergivalverde/plaud-toolkit — TS, no upload, only us/eu regions hardcoded
  - arbuzmell/plaud-api — Python, has upload but no Apple Podcasts integration,
    no APAC region support either
- This package bridges the two and is **agent‑agnostic**: it just produces
  a transcript file and tells you the path. Your agent decides downstream.

## Status

**Alpha.** APIs may change. See [CHANGELOG.md](CHANGELOG.md).

## Install

```bash
pip install apple-podcast-plaud
```

For local dev (recommended — works around a Python 3.14 ``.pth`` bug we hit
in setuptools' editable install on some Macs):

```bash
git clone https://github.com/jumpin-dev/apple-podcast-plaud
cd apple-podcast-plaud
./scripts/dev-install.sh
source .venv/bin/activate
apb --version
```

That script creates a venv, installs the package + dev extras, and writes
both a plain-text ``.pth`` AND a ``PYTHONPATH`` export to
``.venv/bin/activate`` so ``import apple_podcast_plaud`` always works
regardless of whether your Python build honours ``.pth`` files at startup.

## Quickstart

### 1. One-time auth — pick one of two paths

You need a Plaud bearer token. There are two ways to get one — pick whichever
works for your account.

#### Path A — email + password login (only works if your account has a password)

```bash
apb auth login                   # interactive: prompts for email + password
# or
apb auth login --email you@example.com
```

Some accounts (Google sign-in only, no password ever set) **cannot** use
this path; the server will reject every credential pair until you set a
password via the "Forgot password" flow at <https://web.plaud.ai>. If you
hit `wrong account or password` even with the right credentials, switch
to Path B.

#### Path B — paste a token from the web app

Works for every account, including Google-only.

1. Log in to <https://web.plaud.ai>
2. Open DevTools → **Console** (NOT the Local Storage view — that pane
   line-wraps long values and copies will silently include newlines)
3. Run:
   ```js
   copy(localStorage.getItem('tokenstr'))
   ```
4. Save the token:
   ```bash
   apb auth set-token             # interactive: paste then Ctrl-D
   ```
   …or do it by hand:
   ```bash
   mkdir -p ~/.config/plaud && pbpaste > ~/.config/plaud/token && chmod 600 ~/.config/plaud/token
   ```

#### Verify

```bash
apb auth status
# region: apac
# expires: 2027-02-19 (in 299 days)
# server check: ok
```

Tokens last ~10 months; rotate via the same flow when expired.
Detail: [docs/token-extraction.md](docs/token-extraction.md).

### 2. Run

```bash
# Transcribe an episode you've already downloaded in Apple Podcasts.
# Match by keyword in podcast or episode title:
apb transcribe "逆商"

# Override output dir:
apb transcribe "逆商" --out-dir ~/Desktop/podcast-transcripts

# JSON envelope to stdout — your agent reads this:
apb transcribe "逆商" --json-out -
```

### 3. As an MCP server (recommended for Claude Code)

Add this to your Claude Code `settings.json`:

```json
{
  "mcpServers": {
    "podcast-transcribe": {
      "command": "uvx",
      "args": ["apple-podcast-plaud", "mcp"]
    }
  }
}
```

Then just talk to Claude naturally: "帮我转写最新一期播客" or "list my downloaded
podcasts". The MCP server exposes 4 tools:

| Tool | Description |
|------|-------------|
| `list_podcasts` | Query downloaded episodes by keyword |
| `transcribe` | Upload + transcribe an episode via Plaud (2-5 min) |
| `auth_status` | Check if Plaud credentials are configured |
| `auth_login` | Log in with email + password |

For local development, use:

```json
{
  "mcpServers": {
    "podcast-transcribe": {
      "command": "/path/to/apple-podcast-plaud/.venv/bin/python",
      "args": ["-m", "apple_podcast_plaud.mcp"]
    }
  }
}
```

### 4. As a Claude Code skill (legacy)

Drop the `claude-skill/` folder into `~/.claude/skills/apple-podcast-plaud/`,
or symlink it. See [claude-skill/SKILL.md](claude-skill/SKILL.md).

## JSON envelope (output schema)

```json
{
  "status": "ok",
  "podcast": "高情商沟通话术：自在表达，想说就说",
  "episode": "320 逆商：我们该如何应对坏事件？",
  "language": "zh",
  "duration_sec": 1815,
  "segment_count": 48,
  "out_dir": "/Users/.../Documents/podcasts/2026-04-26-逆商",
  "files": {
    "transcript_md": ".../transcript.md",
    "summary_md": ".../summary.md",
    "raw_json": ".../transcript.raw.json",
    "metadata_json": ".../metadata.json"
  },
  "source": "plaud",
  "plaud_recording_id": "e4eb71b...",
  "elapsed_sec": 187
}
```

Full schema: [docs/output-format.md](docs/output-format.md).

## Architecture

```
src/apple_podcast_plaud/
├── plaud/      # Reusable Plaud API client (us/eu/apac region routing,
│               # auth, recordings, transcriptions). Could spin out as
│               # a separate package in the future.
├── bridge/     # Apple-Podcasts ↔ Plaud orchestration: SQLite querying,
│               # language detection, language-routed tracks (Plaud / Apple
│               # TTML), output writers, CLI.
└── mcp/        # MCP server for Claude Code integration — thin wrapper
                # over plaud/ and bridge/ modules.
```

## Acknowledgements

This project is independently implemented but the API surface and request
shapes were initially scouted from the excellent reverse-engineering work in:

- [`arbuzmell/plaud-api`](https://github.com/arbuzmell/plaud-api) — MIT-licensed
  Python Plaud client; the upload pipeline and browser-headers profile here
  were studied from this project before being reimplemented.
- [`sergivalverde/plaud-toolkit`](https://github.com/sergivalverde/plaud-toolkit)
  — MIT-licensed TypeScript Plaud client; the region-redirect detection
  pattern was studied from this project.

Apple Podcasts SQLite/TTML schema is documented across:

- [`mattdanielmurphy/apple-podcast-transcript-extractor`](https://github.com/mattdanielmurphy/apple-podcast-transcript-extractor)
- [`cvonste2/apple-podcast-transcript-tool`](https://github.com/cvonste2/apple-podcast-transcript-tool)
- [`dado3212/apple-podcast-transcripts`](https://github.com/dado3212/apple-podcast-transcripts)

All trademarks belong to their respective owners. This project is not
affiliated with or endorsed by Plaud Inc. or Apple Inc. The Plaud API used
here is reverse-engineered from the public web app and may change without
notice.

## License

MIT. See [LICENSE](LICENSE).
