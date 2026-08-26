"""Persistent memory store: an append-only JSONL log with atomic compaction.

Design goals
------------
* **Crash-safe** — appends are atomic (write-temp-rename); readers never see
  half a line.
* **Human-legible** — plain JSON Lines, one entry per line; you can read it
  in any editor and share it.
* **Git-friendly** — the file can be exported/tracked for team memory.
* **Zero dependencies** — this is the Python standard library doing the work.

Layout: ``<store>/memory.jsonl``; a ``.lock`` file guards writers; ``gc``
rewrites the log atomically and enforces TTLs and the hard cap.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, Iterator, List, Optional, Sequence

from . import util
from .errors import StoreCorruptError, StoreLockedError
from .version import MEMORY_FORMAT_VERSION

KINDS = ("decision", "gotcha", "tip", "api", "convention", "task", "note")

KIND_META = {
    "decision": {"label": "Decision", "icon": "⚖", "color": "#4c8bf5"},
    "gotcha": {"label": "Gotcha", "icon": "⚠", "color": "#f5a623"},
    "tip": {"label": "Tip", "icon": "💡", "color": "#7ed321"},
    "api": {"label": "API", "icon": "🔌", "color": "#9013fe"},
    "convention": {"label": "Convention", "icon": "📐", "color": "#2ec4b6"},
    "task": {"label": "Task", "icon": "✅", "color": "#f78c6c"},
    "note": {"label": "Note", "icon": "📝", "color": "#cccccc"},
}


def new_entry(
    text: str,
    kind: str = "note",
    tags: Optional[Sequence[str]] = None,
    file: Optional[str] = None,
    line: Optional[int] = None,
    source: str = "cli",
    importance: int = 3,
    ttl_days: Optional[int] = None,
    link: Optional[str] = None,
) -> Dict[str, Any]:
    now = int(time.time())
    return {
        "id": util.short_hash(text + str(now), 12),
        "kind": kind if kind in KINDS else "note",
        "text": text.strip(),
        "tags": sorted({t.lower() for t in (tags or []) if t}),
        "file": file or None,
        "line": line,
        "source": source,
        "importance": max(1, min(5, int(importance))),
        "ttl_days": ttl_days,
        "link": link,
        "created_at": now,
        "updated_at": now,
        "fingerprint": util.token_fingerprint(text),
        "format_version": MEMORY_FORMAT_VERSION,
    }


class MemoryStore:
    """Read/write access to a store's memory.jsonl."""

    def __init__(self, store_dir: str, ttl_days: Optional[Dict[str, int]] = None):
        self.store_dir = store_dir
        from .config import store_paths

        self.path = store_paths(store_dir)["memory"]
        self.ttl_defaults = dict(ttl_days or {})

    # -- read ---------------------------------------------------------------

    def read(self) -> List[Dict[str, Any]]:
        if not os.path.exists(self.path):
            return []
        entries: List[Dict[str, Any]] = []
        with open(self.path, "r", encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except ValueError as exc:
                    raise StoreCorruptError(
                        f"{self.path} line {lineno} is not valid JSON: {exc}"
                    ) from exc
                if not isinstance(data, dict):
                    raise StoreCorruptError(f"{self.path} line {lineno} is not an object")
                entries.append(data)
        return entries

    def count(self) -> int:
        if not os.path.exists(self.path):
            return 0
        n = 0
        with open(self.path, "r", encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    n += 1
        return n

    # -- write --------------------------------------------------------------

    def append(self, entry: Dict[str, Any]) -> None:
        with util.file_lock(self.store_dir):
            path = self.path
            os.makedirs(self.store_dir, exist_ok=True)
            # read prior content so append never loses history
            prior: List[str] = []
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8", errors="replace") as fh:
                    prior = fh.readlines()
            line = json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n"
            fd, tmp = _tmp_for(path)
            try:
                with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
                    fh.writelines(prior)
                    fh.write(line)
                    fh.flush()
                    os.fsync(fh.fileno())
                os.replace(tmp, path)
            except BaseException:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise

    def replace(self, entries: Sequence[Dict[str, Any]]) -> None:
        with util.file_lock(self.store_dir):
            os.makedirs(self.store_dir, exist_ok=True)
            fd, tmp = _tmp_for(self.path)
            try:
                with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
                    for entry in entries:
                        fh.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
                    fh.flush()
                    os.fsync(fh.fileno())
                os.replace(tmp, self.path)
            except BaseException:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise

    # -- maintenance ----------------------------------------------------------

    def gc(self, after_entry: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Enforce TTLs and dedupe, rewrite atomically. Returns a report."""
        from .config import store_paths

        hard_cap = 50_000
        try:
            cfg = util.read_json(store_paths(self.store_dir)["config"])
            hard_cap = int(cfg.get("memory_hard_cap", hard_cap) or hard_cap)
        except Exception:
            pass

        entries = self.read()
        now = int(time.time())
        kept: List[Dict[str, Any]] = []
        seen_fp: Dict[str, int] = {}
        expired = skipped_dup = 0
        for e in entries:
            ttl = e.get("ttl_days")
            if ttl is None:
                ttl = self.ttl_defaults.get(e.get("kind", "note"))
            if ttl is not None:
                created = e.get("created_at", 0)
                if now - created > ttl * 86400:
                    expired += 1
                    continue
            fp = e.get("fingerprint") or util.token_fingerprint(e.get("text", ""))
            if fp in seen_fp:
                # keep the newer entry, merge tags
                older_idx = seen_fp[fp]
                kept[older_idx]["tags"] = sorted(set(kept[older_idx].get("tags", [])) | set(e.get("tags", [])))
                skipped_dup += 1
                continue
            seen_fp[fp] = len(kept)
            kept.append(e)

        # enforce the hard cap by dropping oldest lowest-importance entries
        if len(kept) > hard_cap:
            over = len(kept) - hard_cap
            kept.sort(key=lambda e: (e.get("importance", 3), -e.get("created_at", 0)))
            kept = kept[over:]
            kept.sort(key=lambda e: e.get("created_at", 0))
            skipped_dup += over
        self.replace(kept)
        return {
            "before": len(entries),
            "after": len(kept),
            "expired": expired,
            "deduped": skipped_dup,
        }


def _tmp_for(path: str) -> tuple:
    import tempfile

    directory = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(prefix=os.path.basename(path) + ".", suffix=".tmp", dir=directory)
    return fd, tmp