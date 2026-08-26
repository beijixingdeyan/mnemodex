"""Memory domain logic: the operations the CLI, MCP and web UI share.

This layer owns the *rules* of memory:

* kind detection (autocategorize) when the user doesn't say what it is,
* dedupe by fingerprint so agents don't write the same fact twice,
* relevance ranking by recency, importance and text overlap,
* markdown export for sharing (team memory, git-tracked).

Persistence lives in :mod:`mnemodex.store`; this module has zero I/O side
effects of its own.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import util
from .store import KINDS, KIND_META, MemoryStore, new_entry

_KIND_HINTS: List[Tuple[str, Tuple[str, ...]]] = [
    ("decision", ("we decided", "decided to", "decision", "we chose", "chosen", "agreed on",
                  "design decision", "will use", "we use", "we will")),
    ("gotcha", ("gotcha", "got bitten", "got burned", "watch out", "beware", "pitfall",
                "careful", "breaks", "breaks if", "surprising", "gotcha:", "trick", "got stuck",
                "does not work", "doesn't work", "failed", "failure")),
    ("api", ("signature", "takes", "returns", "params", "parameter", "endpoint", "api", "sdk",
             "function", "method", "interface", "argument", "callback", "response", "payload",
             "headers", "auth", "token")),
    ("convention", ("convention", "style", "naming", "format", "pattern", "consistent",
                    "always", "usually", "normally", "standard")),
    ("task", ("todo", "to do", "follow-up", "follow up", "later", "next step", "fix", "bpf",
              "need to", "should", "must", "remember to")),
    ("tip", ("tip", "faster", "better", "instead", "recommend", "try", "use this", "pro tip",
             "simpler", "cleaner", "workaround")),
]


def autocategorize(text: str) -> str:
    """Guess a memory kind from the text's phrasing (deterministic)."""
    low = text.lower()
    for kind, hints in _KIND_HINTS:
        for hint in hints:
            if hint in low:
                return kind
    return "note"


def valid_kind(kind: Optional[str]) -> str:
    if kind in KINDS:
        return kind
    return "note"


def normalize_tags(tags: Optional[Sequence[str]]) -> List[str]:
    out: List[str] = []
    for tag in tags or []:
        for piece in re.split(r"[,\s]+", str(tag)):
            piece = piece.strip().lower()
            if piece and piece not in out and len(piece) <= 40:
                out.append(piece)
    return out


class Memory:
    """Facade over MemoryStore with the domain rules."""

    def __init__(self, store_dir: str, ttl_days: Optional[Dict[str, int]] = None):
        self.store = MemoryStore(store_dir, ttl_days=ttl_days)

    # -- add ----------------------------------------------------------------

    def add(
        self,
        text: str,
        kind: Optional[str] = None,
        tags: Optional[Sequence[str]] = None,
        file: Optional[str] = None,
        line: Optional[int] = None,
        source: str = "cli",
        importance: int = 3,
        ttl: Optional[int] = None,
        auto_kind: bool = True,
        dedupe_window: int = 200,
    ) -> Dict[str, Any]:
        text = (text or "").strip()
        if not text:
            raise ValueError("memory text must not be empty")
        if kind:
            effective_kind = valid_kind(kind)
        elif auto_kind:
            effective_kind = autocategorize(text)
        else:
            effective_kind = "note"
        entry = new_entry(
            text,
            effective_kind,
            normalize_tags(tags),
            file=file,
            line=line,
            source=source,
            importance=importance,
            ttl_days=ttl,
        )
        # dedupe within the recent tail
        recent = self.store.read()[-dedupe_window:]
        for older in recent:
            if older.get("fingerprint") == entry["fingerprint"]:
                return {
                    "entry": older,
                    "duplicate": True,
                    "message": f"duplicate of existing entry {older['id']}",
                }
        self.store.append(entry)
        return {"entry": entry, "duplicate": False, "message": f"stored as {entry['id']}"}

    # -- query ----------------------------------------------------------------

    def get(self, entry_id: str) -> Optional[Dict[str, Any]]:
        for e in self.store.read():
            if e.get("id") == entry_id:
                return e
        return None

    def update(self, entry_id: str, **fields: Any) -> Optional[Dict[str, Any]]:
        entries = self.store.read()
        for e in entries:
            if e.get("id") == entry_id:
                for key, value in fields.items():
                    if key in ("text", "kind", "tags", "file", "line", "importance", "ttl_days", "link"):
                        if key == "text" and value:
                            e["text"] = str(value).strip()
                            e["fingerprint"] = util.token_fingerprint(e["text"])
                        elif key == "tags":
                            e["tags"] = normalize_tags(value)
                        else:
                            e[key] = value
                e["updated_at"] = int(__import__("time").time())
                self.store.replace(entries)
                return e
        return None

    def forget(self, entry_id: str) -> bool:
        entries = self.store.read()
        kept = [e for e in entries if e.get("id") != entry_id]
        if len(kept) == len(entries):
            return False
        self.store.replace(kept)
        return True

    def forget_matching(self, query: str) -> int:
        """Forget every entry matching a text query. Returns removed count."""
        words = set(util.split_words(query))
        entries = self.store.read()
        kept = [e for e in entries if not _text_matches(e, words)]
        removed = len(entries) - len(kept)
        if removed:
            self.store.replace(kept)
        return removed

    def recall(
        self,
        query: Optional[str] = None,
        kind: Optional[str] = None,
        tag: Optional[str] = None,
        limit: int = 20,
        file: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Rank entries by relevance (query) then recency × importance."""
        all_entries = self.store.read()
        words = set(util.split_words(query)) if query else set()
        scored: List[Tuple[float, Dict[str, Any]]] = []
        for e in all_entries:
            if kind and e.get("kind") != kind:
                continue
            if tag and tag not in e.get("tags", []):
                continue
            if file and not (e.get("file") and file in e.get("file", "")):
                continue
            score = 0.0
            if words:
                text_words = set(util.split_words(e.get("text", "")))
                overlap = len(words & text_words)
                if overlap == 0:
                    # substring fallback: "cache" should find "cached"
                    sub_hits = sum(1 for w in words if any(w in tw for tw in text_words))
                    if sub_hits == 0:
                        continue  # strict-ish: memory must be on-topic
                    score += 1.5 * sub_hits
                else:
                    score += 4.0 * overlap
                for w in words:
                    if w in e.get("text", "").lower():
                        score += 1.0
                if file:
                    score += 3.0
            elif not kind and not tag:
                score = 0.0  # listing mode — no relevance component
            recency = _recency_bonus(e.get("created_at", 0))
            score += recency + 0.5 * e.get("importance", 3)
            if not words and not kind and not tag:
                score = recency + 0.5 * e.get("importance", 3)
            scored.append((score, e))
        scored.sort(key=lambda t: (-t[0], -t[1].get("created_at", 0)))
        return [e for _, e in scored[:limit]]

    def list_all(self, limit: int = 200) -> List[Dict[str, Any]]:
        return self.recall(limit=limit)

    def stats(self) -> Dict[str, int]:
        counts: Dict[str, int] = {k: 0 for k in KINDS}
        total = 0
        for e in self.store.read():
            counts[e.get("kind", "note")] = counts.get(e.get("kind", "note"), 0) + 1
            total += 1
        return {"total": total, **counts}

    def export_markdown(self, kind: Optional[str] = None, tag: Optional[str] = None) -> str:
        """Render all entries as a shareable markdown doc (team memory)."""
        entries = [e for e in self.store.read() if (not kind or e.get("kind") == kind) and (not tag or tag in e.get("tags", []))]
        entries.sort(key=lambda e: (-e.get("created_at", 0)))
        lines = ["# Repository Memory", "", "_Generated by mnemodex — edit freely, changes are tracked_", ""]
        for k in KINDS:
            subset = [e for e in entries if e.get("kind") == k]
            if not subset:
                continue
            meta = KIND_META[k]
            lines.append(f"## {meta['icon']} {meta['label']}")
            lines.append("")
            for e in subset:
                where = f" · `{e['file']}@{e['line']}`" if e.get("file") else ""
                tags = " ".join(f"`#{t}`" for t in e.get("tags", []))
                lines.append(f"- **{e['id'][:8]}** ({util.time_ago(e['created_at'])}){where}{' ' + tags if tags else ''}")
                lines.append(f"  {e.get('text', '')}")
            lines.append("")
        lines.append(f"---\n_Total: {len(entries)} entries._")
        return "\n".join(lines)

    def export_json(self) -> List[Dict[str, Any]]:
        return self.store.read()


def _recency_bonus(created: int) -> float:
    import time

    age_hours = max(0, (int(time.time()) - created)) / 3600.0
    return 6.0 / (1.0 + age_hours / 24.0)  # 0..6, halving every day


def _text_matches(entry: Dict[str, Any], words: set) -> bool:
    if not words:
        return False
    text_words = set(util.split_words(entry.get("text", "")))
    return bool(words & text_words)