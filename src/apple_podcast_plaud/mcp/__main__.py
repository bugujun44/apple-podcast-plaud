"""Entry point for ``python -m apple_podcast_plaud.mcp``."""

from apple_podcast_plaud.mcp.server import mcp

if __name__ == "__main__":
    mcp.run()
