"""Console rendering helpers: ANSI colors, tables, trees, banners.

Color is auto-disabled when stdout is not a TTY or when MNEMODEX_NO_COLOR
is set — piping `mnemodex` output stays clean, and tests stay deterministic.
"""

from __future__ import annotations

import os
import shutil
import sys
from typing import Any, Dict, Iterable, List, Optional, Sequence

_USE_COLOR = (
    os.environ.get("MNEMODEX_NO_COLOR", "") == ""
    and hasattr(sys.stdout, "isatty")
    and sys.stdout.isatty()
)

_CODE = {
    "reset": "\x1b[0m",
    "bold": "\x1b[1m",
    "dim": "\x1b[2m",
    "red": "\x1b[31m",
    "green": "\x1b[32m",
    "yellow": "\x1b[33m",
    "blue": "\x1b[34m",
    "magenta": "\x1b[35m",
    "cyan": "\x1b[36m",
    "white": "\x1b[37m",
    "bg_blue": "\x1b[44m",
    "grey": "\x1b[90m",
}


def paint(text: str, *styles: str) -> str:
    if not _USE_COLOR or not styles:
        return text
    prefix = "".join(_CODE.get(s, "") for s in styles)
    return prefix + text + _CODE["reset"]


def box(text: str, width: Optional[int] = None) -> str:
    lines = text.splitlines()
    w = width or max((len(l) for l in lines), default=0) + 4
    top = "┌" + "─" * w + "┐"
    bottom = "└" + "─" * w + "┘"
    body = [f"│ {l:<{w-2}} │" for l in lines]
    return "\n".join([top, *body, bottom])


def banner() -> str:
    lines = [
        paint("🧠 mnemodex", "bold", "cyan"),
        paint("The memory index for AI coding agents — zero dependencies", "dim"),
    ]
    return "\n".join(lines)


def table(rows: Sequence[Sequence[str]], headers: Optional[Sequence[str]] = None, max_col: int = 60) -> str:
    if not rows:
        return "(no results)"
    grid: List[List[str]] = []
    for row in rows:
        grid.append([str(c) for c in row])
    if headers:
        grid.insert(0, [str(h) for h in headers])
    widths = [max(len(r[i]) if i < len(r) else 0 for r in grid) for i in range(len(grid[0]))]
    out: List[str] = []
    for ridx, row in enumerate(grid):
        cells = []
        for i, cell in enumerate(row):
            text = cell
            if len(text) > max_col:
                text = text[: max_col - 1] + "…"
            cells.append(text.ljust(widths[i]))
        out.append("  ".join(cells).rstrip())
        if headers and ridx == 0:
            out.append("  ".join("─" * w for w in widths))
    return "\n".join(out)


def tree(items: Iterable[str], root: str = ".") -> str:
    """Render a path list as a compact tree."""
    items = sorted(set(items))
    if not items:
        return root
    nodes: Dict[str, Any] = {}
    for path in items:
        parts = path.split("/")
        cur = nodes
        for part in parts:
            cur = cur.setdefault(part, {})
    lines: List[str] = []

    def walk(node: Dict[str, Any], prefix: str, is_last: bool, is_root: bool) -> None:
        keys = sorted(node.keys())
        for idx, key in enumerate(keys):
            last = idx == len(keys) - 1
            connector = "└── " if last else "├── "
            lines.append(prefix + connector + paint(key, "cyan" if node[key] else "white"))
            if node[key]:
                walk(node[key], prefix + ("    " if last else "│   "), last, False)

    walk(nodes, "", True, True)
    return "\n".join(lines)


def status(msg: str, ok: bool = True) -> str:
    mark = paint("✓", "green") if ok else paint("✗", "red")
    return f"{mark} {msg}"


def section(title: str) -> str:
    return paint("── " + title + " " + "─" * max(0, 40 - len(title)), "bold")


def width() -> int:
    try:
        return shutil.get_terminal_size((80, 24)).columns
    except Exception:
        return 80


def pager(text: str) -> None:
    """Print text, optionally piping through `less -R` on POSIX TTYs."""
    if sys.stdout.isatty() and os.name == "posix" and shutil.which("less"):
        import subprocess

        proc = subprocess.Popen(["less", "-R"], stdin=subprocess.PIPE)
        try:
            proc.communicate(text.encode("utf-8"))
        except BrokenPipeError:
            pass
    else:
        print(text)


def spinners() -> List[str]:
    return ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]