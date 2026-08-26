"""
mnemodex — the memory index for AI coding agents.

Mnemodex gives coding agents (Claude Code, Cursor, Codex, Cline, ...) a
durable, queryable, local-first memory of your repository:

  * a knowledge graph of files, symbols, imports and references,
  * a persistent memory store for decisions, gotchas, conventions and APIs,
  * a zero-dependency MCP server so any agent can read & write it,
  * a terminal CLI and a zero-dependency web UI.

The entire project is implemented against the Python standard library only.

.. moduleauthor:: Mnemodex Contributors
"""

from .version import __version__, VERSION

__all__ = ["__version__", "VERSION", "mnemodex_version"]


def mnemodex_version() -> str:
    """Return the installed mnemodex version string."""
    return __version__