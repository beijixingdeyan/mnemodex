"""Optional git integration for mnemodex.

The indexer itself is git-agnostic (it reads files, not history), but when
`git` is available mnemodex can enrich the store with recency signals:

* recently *touched* files (for freshest-context during `ask`),
* hot files by commit count (you changed them a lot ⇒ they matter),
* recent commit subjects (why did this change?).

Every function degrades gracefully: no git binary, not a repo, or a command
failing → empty results. The store never leaks absolute paths.
"""

from __future__ import annotations

import os
import re
import subprocess
from typing import Any, Dict, List, Optional, Tuple

_GIT_EXE = "git"


def _git_available() -> bool:
    try:
        subprocess.run([_GIT_EXE, "--version"], capture_output=True, timeout=10)
        return True
    except Exception:
        return False


def _run(root: str, args: List[str], timeout: int = 15) -> Optional[str]:
    try:
        proc = subprocess.run(
            [_GIT_EXE, "-C", root] + args,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout


def is_git_repo(root: str) -> bool:
    out = _run(root, ["rev-parse", "--is-inside-work-tree"])
    return out is not None and out.strip() == "true"


def recent_commits(root: str, count: int = 10) -> List[Dict[str, Any]]:
    """Recent commit subjects: [{hash, subject, author, date_ts}]."""
    out = _run(
        root,
        ["log", f"-{count}", "--pretty=format:%H%x01%s%x01%an%x01%at"],
    )
    if not out:
        return []
    commits: List[Dict[str, Any]] = []
    for line in out.splitlines():
        parts = line.split("\x01")
        if len(parts) == 4:
            commits.append(
                {
                    "hash": parts[0][:12],
                    "subject": parts[1],
                    "author": parts[2],
                    "date": int(parts[3] or 0),
                }
            )
    return commits


def touched_files(root: str, since_days: int = 14, limit: int = 30) -> List[Dict[str, Any]]:
    """Files modified in recent commits, newest first: [{path, commits}]."""
    out = _run(
        root,
        ["log", f"--since={since_days}.days", "--name-only", "--pretty=format:%H"],
    )
    if not out:
        return []
    seen: Dict[str, int] = {}
    for line in out.splitlines():
        line = line.strip()
        if not line or len(line) == 40 or line.startswith("commit "):
            continue
        if line in seen:
            continue
        seen[line] = 1
        if len(seen) >= limit:
            break
    return [{"path": p, "commits": 1} for p in seen if not p.startswith(("..", "/"))]


def hot_files(root: str, limit: int = 20) -> List[Tuple[str, int]]:
    """Files ranked by how many commits touched them: (path, commit_count)."""
    counts: Dict[str, int] = {}
    out = _run(root, ["log", "--pretty=format:%H", "--name-only", "-500"])
    if not out:
        return []
    current = None
    for line in out.splitlines():
        line = line.strip()
        if len(line) == 40:
            current = line
            continue
        if not line or line.startswith(("..", "/")):
            continue
        counts[line] = counts.get(line, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: -kv[1])
    return ranked[:limit]


def changed_files_between(root: str, ref_a: str = "HEAD~1", ref_b: str = "HEAD") -> List[str]:
    out = _run(root, ["diff", "--name-only", ref_a, ref_b])
    if not out:
        return []
    return [ln for ln in out.splitlines() if ln and not ln.startswith(("..", "/"))]


def current_branch(root: str) -> Optional[str]:
    out = _run(root, ["branch", "--show-current"])
    return out.strip() if out else None


def summarise(root: str, limit_commits: int = 5, limit_hot: int = 10) -> Dict[str, Any]:
    """All git signals in one call (used by `ask` and the MCP context tool)."""
    if not is_git_repo(root):
        return {"available": False}
    return {
        "available": True,
        "branch": current_branch(root),
        "recent_commits": recent_commits(root, limit_commits),
        "hot_files": [p for p, _ in hot_files(root, limit_hot)],
        "touched": [t["path"] for t in touched_files(root, limit=limit_hot)],
    }