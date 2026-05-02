#!/usr/bin/env bash
# MCP server launcher — works around Python 3.14 .pth honouring bug.
# Claude Code calls this script; it sets PYTHONPATH then runs the server.
SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
export PYTHONPATH="${SCRIPT_DIR}/src:${PYTHONPATH:-}"
exec "${SCRIPT_DIR}/.venv/bin/python" -m apple_podcast_plaud.mcp "$@"
