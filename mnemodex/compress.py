"""Context compression: pack the right knowledge into a token budget.

When an agent asks mnemodex for context, we must not dump the whole store —
we must *select* what matters, in order of diminishing returns:

    1. exact matches in memory (decisions / gotchas about the topic),
    2. declarations of the symbols they asked about (with one-line sigs),
    3. the files that *define* those symbols (snippets),
    4. import neighbourhood (files that import them → blast radius),
    5. recently touched files (git-aware when available).

Every section reports its token estimate, and the selector stops when the
budget is consumed — the output is always parseable and size-bounded.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import graph as graph_mod
from . import util
from .graph import EDGE_IMPORT, EDGE_REF, KnowledgeGraph, file_id
from .search import SearchIndex


class ContextPack:
    """A size-bounded, ordered selection of context material."""

    def __init__(self, budget_tokens: int = 8000):
        self.budget = budget_tokens
        self.sections: List[Dict[str, Any]] = []
        self.used = 0

    def add(self, title: str, body: str, meta: Optional[Dict[str, Any]] = None) -> bool:
        """Add a section if it fits the remaining budget. Returns True if added."""
        tokens = util.estimate_tokens(body)
        if self.used + tokens > self.budget:
            # always allow the first section even if oversized (better than empty)
            if not self.sections:
                self.used += tokens
                self.sections.append({"title": title, "body": body, "tokens": tokens, **(meta or {})})
                return True
            return False
        self.used += tokens
        self.sections.append({"title": title, "body": body, "tokens": tokens, **(meta or {})})
        return True

    def render(self) -> str:
        out: List[str] = []
        for section in self.sections:
            out.append(f"## {section['title']}")
            out.append("")
            out.append(section["body"])
            out.append("")
        if not out:
            out.append("_(no context matches — index is empty or query is too specific)_")
        header = f"mnemodex context pack · {self.used}/{self.budget} tokens"
        return header + "\n\n" + "\n".join(out).strip()


def _symbol_section(symbols: List[graph_mod.Node], max_items: int = 25) -> str:
    lines: List[str] = []
    for node in symbols[:max_items]:
        name = node.attrs.get("name", "?")
        kind = node.attrs.get("kind", "?")
        path = node.attrs.get("path", "?")
        line = node.attrs.get("line", "?")
        sig = node.attrs.get("signature", "")
        lines.append(f"- {name} ({kind}) — `{path}:{line}` {sig}")
    return "\n".join(lines) if lines else "_(no symbols found)_"


def _snippet_block(repo_root: str, records: Sequence[Tuple[str, int]], max_chars: int = 3000) -> str:
    out: List[str] = []
    used = 0
    for path, line in records:
        from .indexer import read_snippet

        text = read_snippet(repo_root, path, max(1, line - 1), span=6)
        if text and used + len(text) <= max_chars:
            out.append(text)
            used += len(text)
    return "\n".join(out) if out else "_(no source snippets)_"


def build_context(
    query: str,
    *,
    search_index: SearchIndex,
    memory_entries: List[Dict[str, Any]],
    graph: KnowledgeGraph,
    repo_root: str,
    budget_tokens: int = 8000,
    max_symbols: int = 25,
    max_files: int = 15,
) -> ContextPack:
    """Assemble a :class:`ContextPack` for a free-text agent query."""
    pack = ContextPack(budget_tokens)

    # 1 — memory
    if memory_entries:
        lines = []
        for e in memory_entries[:12]:
            where = f"`{e['file']}@{e['line']}`" if e.get("file") else "repo"
            tags = " ".join(f"#{t}" for t in e.get("tags", [])[:5])
            lines.append(
                f"- [{e.get('kind', 'note')}] {e.get('text', '')} "
                f"(_via_ {where}, {util.time_ago(e.get('created_at', 0))} · {tags})".strip()
            )
        pack.add("Relevant memory", "\n".join(lines), {"source": "memory"})

    # 2,3 — symbols & defining files
    interesting = _interesting_symbols(query, search_index, graph, max_symbols)
    if interesting:
        pack.add("Symbols", _symbol_section(interesting), {"source": "symbols"})
        defining = [
            (node.attrs.get("path"), int(node.attrs.get("line", 1)))
            for node in interesting
            if node.attrs.get("path")
        ]
        dedup: List[Tuple[str, int]] = []
        seen_paths: set = set()
        for path, line in defining:
            if path not in seen_paths:
                seen_paths.add(path)
                dedup.append((path, line))
        pack.add("Definitions (snippets)", _snippet_block(repo_root, dedup), {"source": "snippets"})

    # 4 — blast radius: what imports these files?
    files: List[str] = []
    for node in interesting:
        path = node.attrs.get("path")
        if path and path not in files:
            files.append(path)
    dependent = _dependents(graph, files, limit=max_files)
    if dependent:
        lines = "\n".join(f"- `{p}` (imports the target)" for p in dependent)
        pack.add("Impact / dependents", lines, {"source": "dependents"})

    # 5 — hot files (only if budget remains)
    if pack.used < budget_tokens * 0.7:
        hot = sorted(search_index.files.values(), key=lambda f: f.size, reverse=True)[:6]
        lines = "\n".join(
            f"- `{f.path}` ({f.language}, {f.lines} lines, {len(f.symbols)} symbols)"
            for f in hot
        )
        if lines:
            pack.add("Largest indexed files", lines, {"source": "sizes"})

    return pack


def _interesting_symbols(query: str, search_index: SearchIndex, graph: KnowledgeGraph, limit: int) -> List[graph_mod.Node]:
    """Pick symbol nodes matching the query terms, then by page-rank tiebreak."""
    words = set(util.split_words(query))
    scored: List[Tuple[float, graph_mod.Node]] = []
    pr = graph.page_rank(iterations=15)
    for node in graph.nodes.values():
        if node.kind != graph_mod.NODE_SYMBOL:
            continue
        name = node.attrs.get("name", "").lower()
        s = 0.0
        for w in words:
            if w in name:
                s += 2.0
                if name.startswith(w):
                    s += 1.0
        if s == 0 and words:
            continue
        s += 1.5 * pr.get(node.id, 0.0)
        scored.append((s, node))
    scored.sort(key=lambda t: (-t[0], t[1].attrs.get("path", "")))
    return [n for _, n in scored[:limit]]


def _dependents(graph: KnowledgeGraph, files: Sequence[str], limit: int) -> List[str]:
    out: List[str] = []
    for path in files:
        targets = {file_id(path)}
        for edge in graph.edges:
            if edge.type == EDGE_REF and edge.dst in targets and edge.src.startswith("f:"):
                src_path = edge.src[2:]
                if src_path not in out and src_path not in files:
                    out.append(src_path)
    return out[:limit]


def suggest_memory_kind(query: str, text: str) -> str:
    """Expose autocategorize for the MCP `add` tool when kind is omitted."""
    from .memory import autocategorize

    return autocategorize(query + " " + text)