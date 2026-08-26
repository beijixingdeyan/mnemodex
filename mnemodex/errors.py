"""Central error types for mnemodex.

All expected failure modes raise one of these; the CLI layer converts them
into clean exit codes and the MCP layer converts them into JSON-RPC error
responses.
"""

from __future__ import annotations

from typing import Iterable, Optional


class MnemodexError(Exception):
    """Base class for every mnemodex error.

    Attributes
    ----------
    exit_code : int
        Process exit code the CLI should use when this error reaches the top
        level.
    hints : tuple[str, ...]
        Human-readable remediation hints appended to the message.
    """

    exit_code = 1

    def __init__(self, message: str, hints: Optional[Iterable[str]] = None):
        super().__init__(message)
        self.message = message
        self.hints = tuple(hints or ())

    def pretty(self) -> str:
        """Render the error with hints for console output."""
        parts = [self.message]
        for hint in self.hints:
            parts.append(f"  -> {hint}")
        return "\n".join(parts)


class ConfigError(MnemodexError):
    """Configuration is missing, malformed or contradictory."""

    exit_code = 2


class NotInitializedError(MnemodexError):
    """The current repository has no `.mnemodex/` store yet.

    Raised when a command that requires a store runs outside an initialized
    repo. The fix is `mnemodex init`.
    """

    exit_code = 3

    def __init__(self, cwd: str, hints: Optional[Iterable[str]] = None):
        default_hints = (
            f"Run `mnemodex init` inside {cwd!r} to create the store.",
            "Export MNEMODEX_HOME to force a store location.",
        )
        super().__init__(
            f"no mnemodex store found in this repository (searched {cwd!r})",
            hints or default_hints,
        )


class IndexMissingError(MnemodexError):
    """The store exists but has no index yet."""

    exit_code = 4

    def __init__(self) -> None:
        super().__init__(
            "the repository index has not been built yet",
            ("Run `mnemodex index` to build the code knowledge graph.",),
        )


class LexError(MnemodexError):
    """The lexer hit a construct it cannot tokenize."""

    exit_code = 5


class UnsupportedLanguageError(MnemodexError):
    """A file extension is not covered by any registered language."""

    exit_code = 6


class StoreCorruptError(MnemodexError):
    """The on-disk store failed validation (bad JSON, bad schema, ...)."""

    exit_code = 7


class StoreLockedError(MnemodexError):
    """Another process holds the store lock."""

    exit_code = 8

    def __init__(self, lock_path: str) -> None:
        super().__init__(
            f"store is locked by another process ({lock_path})",
            ("If the lock is stale, remove the file and retry.",),
        )


class ValidationError(MnemodexError):
    """A user-supplied argument failed semantic validation."""

    exit_code = 9


class McpError(MnemodexError):
    """An MCP protocol level problem."""

    exit_code = 10


class GitNotAvailableError(MnemodexError):
    """The optional git integration could not find `git`."""

    exit_code = 11


class WebUiError(MnemodexError):
    """The web UI server failed to start."""

    exit_code = 12