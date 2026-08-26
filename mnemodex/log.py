"""Tiny, dependency-free logging for mnemodex.

Designed so the MCP server can capture structured logs without polluting
its stdio channel (MCP speaks JSON-RPC over stdio; any stray text would
corrupt the protocol) — logs go to stderr, or to a file when `--log-file`
is given.
"""

from __future__ import annotations

import os
import sys
import time
from typing import Dict, Optional

_LEVELS = {"debug": 10, "info": 20, "warn": 30, "error": 40, "quiet": 50}


class Logger:
    """Minimal leveled logger writing to stderr or a file."""

    def __init__(self, name: str = "mnemodex", level: str = "info", path: Optional[str] = None):
        self.name = name
        self.level = _LEVELS.get(level, 20)
        self.path = path
        if path:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    def set_level(self, level: str) -> None:
        self.level = _LEVELS.get(level, self.level)

    def _emit(self, level: str, level_no: int, msg: str, **kw: object) -> None:
        if level_no < self.level:
            return
        line = f"{time.strftime('%H:%M:%S')} {level.upper():<5} {msg}"
        if kw:
            line += " " + " ".join(f"{k}={v}" for k, v in kw.items())
        try:
            if self.path:
                with open(self.path, "a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
            else:
                print(line, file=sys.stderr, flush=True)
        except OSError:
            pass

    def debug(self, msg: str, **kw: object) -> None:
        self._emit("debug", 10, msg, **kw)

    def info(self, msg: str, **kw: object) -> None:
        self._emit("info", 20, msg, **kw)

    def warn(self, msg: str, **kw: object) -> None:
        self._emit("warn", 30, msg, **kw)

    def error(self, msg: str, **kw: object) -> None:
        self._emit("error", 40, msg, **kw)


_default: Optional[Logger] = None
_loggers: Dict[str, Logger] = {}


def get_logger(name: str = "mnemodex") -> Logger:
    """Return the process-wide logger singleton for *name*."""
    global _default
    if _default is None:
        _default = Logger(name)
    return _default


def configure(level: str = "info", path: Optional[str] = None) -> Logger:
    """Configure the process-wide logger. Returns the logger."""
    global _default
    _default = Logger("mnemodex", level=level, path=path)
    return _default