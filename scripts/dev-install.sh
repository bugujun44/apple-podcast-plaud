#!/usr/bin/env bash
# One-shot dev environment bootstrap.
#
# Why this exists: setuptools' modern editable install (the
# ``__editable__.<pkg>.pth`` file generated as of setuptools ~64) is not
# reliably picked up by Python 3.14 — ``import <pkg>`` fails even though
# ``pip install -e .`` reports success. We work around it by writing a
# plain ``<pkg>.pth`` file containing the ``src/`` directory path, which
# Python 3.14 honours unconditionally.
#
# Idempotent: safe to re-run after a ``git pull``.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

VENV_DIR=".venv"

if [[ ! -d "$VENV_DIR" ]]; then
    echo "==> Creating virtualenv in $VENV_DIR"
    python3 -m venv "$VENV_DIR"
fi

# shellcheck source=/dev/null
source "$VENV_DIR/bin/activate"

echo "==> Installing package + dev extras"
pip install -q -e ".[dev]"

# Detect the actual Python version directory (don't hard-code 3.14)
PY_TAG="$(python -c 'import sys; print(f"python{sys.version_info.major}.{sys.version_info.minor}")')"
SITE_PACKAGES="$VENV_DIR/lib/$PY_TAG/site-packages"

if [[ ! -d "$SITE_PACKAGES" ]]; then
    echo "WARN: $SITE_PACKAGES not found; pip layout differs from expected." >&2
    exit 1
fi

# Remove the broken setuptools-generated .pth (any version of the file)
rm -f "$SITE_PACKAGES"/__editable__.apple_podcast_plaud-*.pth

# Write our own plain-text .pth — Python's standard mechanism.
PTH_FILE="$SITE_PACKAGES/apple_podcast_plaud.pth"
echo "$ROOT_DIR/src" > "$PTH_FILE"
echo "==> Wrote $PTH_FILE"

# Belt-and-suspenders: append a PYTHONPATH export to activate as well, in
# case .pth processing is unreliable on this Python build (we have seen
# Python 3.14 fail to honour .pth files in some environments).
ACTIVATE_FILE="$VENV_DIR/bin/activate"
ACTIVATE_MARKER="# apple-podcast-plaud src-layout PYTHONPATH (managed by scripts/dev-install.sh)"
if ! grep -qF "$ACTIVATE_MARKER" "$ACTIVATE_FILE"; then
    {
        echo ""
        echo "$ACTIVATE_MARKER"
        echo "export PYTHONPATH=\"$ROOT_DIR/src:\${PYTHONPATH:-}\""
    } >> "$ACTIVATE_FILE"
    echo "==> Patched $ACTIVATE_FILE with PYTHONPATH fallback"
fi

# Smoke-check the install
python -c "import apple_podcast_plaud, sys; \
    print(f'OK: apple_podcast_plaud {apple_podcast_plaud.__version__} ' \
          f'@ {apple_podcast_plaud.__file__}')"
echo "==> apb available at: $(which apb)"
echo ""
echo "Done. Run:  source .venv/bin/activate  &&  apb --help"
