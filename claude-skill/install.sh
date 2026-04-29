#!/usr/bin/env bash
# Install / update this skill into ~/.claude/skills/ via a symlink.
#
# After running this, `apple-podcast-plaud` shows up in the Claude Code
# skill registry alongside any other global skills. The link points at
# the project repo, so `git pull` updates the skill automatically.
#
# Idempotent: re-running just refreshes the symlink.
set -euo pipefail

SKILL_NAME="apple-podcast-plaud"
SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_PARENT="$HOME/.claude/skills"
TARGET_LINK="$TARGET_PARENT/$SKILL_NAME"

mkdir -p "$TARGET_PARENT"

if [[ -e "$TARGET_LINK" || -L "$TARGET_LINK" ]]; then
    if [[ -L "$TARGET_LINK" ]]; then
        echo "==> Replacing existing symlink: $TARGET_LINK"
    else
        echo "==> Replacing existing real directory: $TARGET_LINK"
        echo "    (its contents are preserved at: $TARGET_LINK.bak)"
        mv "$TARGET_LINK" "$TARGET_LINK.bak"
    fi
    rm -f "$TARGET_LINK"
fi

ln -s "$SOURCE_DIR" "$TARGET_LINK"

echo "==> Linked: $TARGET_LINK -> $SOURCE_DIR"
echo ""
echo "Skill installed. Reload Claude Code (or open a new session) and the"
echo "'$SKILL_NAME' skill will be available."
echo ""
echo "Required: 'apb' must be on PATH for the skill to call out to it."
echo "If you used scripts/dev-install.sh, just 'source .venv/bin/activate'"
echo "in any shell where you want Claude Code to run."
