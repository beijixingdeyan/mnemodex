"""The repository indexer: turns a codebase into Mnemodex's index.

Pipeline per file
-----------------
    1. walk (respecting .gitignore / hidden / depth / size limits)
    2. classify language by name/extension
    3. tokenize + count stats
    4. extract symbols & imports
    5. collect term frequencies for search

Global passes
-------------
    6. resolve imports to repo files (import edges in the graph)
    7. find cross-file references (`ref` edges) from token streams
    8. serialize ``index.json`` (search index + graph + summary)
"""

from __future__ import annotations

import os
import posixpath
import re
import time
from collections import Counter, defaultdict
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple

from . import languages, lexer, search, symbols, util
from .errors import StoreCorruptError
from .gitignore import IncrementalIgnore
from .graph import EDGE_CONTAINS, EDGE_DEFINE, EDGE_IMPORT, EDGE_REF, KnowledgeGraph, file_id, symbol_id
from .search import FileEntry, SearchIndex, SymbolHit
from .version import INDEX_FORMAT_VERSION


def read_snippet(repo_root: str, rel_path: str, start_line: int, span: int = 8) -> str:
    """Read a source snippet for context assembly (used by MCP/web).

    *rel_path* must be repo-relative; traversal is refused.
    """
    if rel_path.startswith("/") or ".." in rel_path.replace("\\", "/").split("/"):
        return ""
    full = os.path.normpath(os.path.join(repo_root, rel_path))
    if not os.path.isfile(full):
        return ""
    try:
        with open(full, "r", encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
    except OSError:
        return ""
    start = max(1, start_line)
    end = min(len(lines), start_line + span)
    if start > len(lines):
        return ""
    body = "".join(lines[start - 1 : end])
    return f"{rel_path}#L{start}\n{body}"


class ImportResolver:
    """Best-effort mapping from an import declaration to repo files."""

    def __init__(self, search_index: SearchIndex):
        self.index = search_index
        # basename -> candidate paths for quick joins
        self._by_basename: Dict[str, List[str]] = defaultdict(list)
        self._by_segments: Dict[str, List[str]] = defaultdict(list)
        for path in search_index.files:
            base = os.path.basename(path)
            self._by_basename[base].append(path)
            stem = os.path.splitext(base)[0]
            self._by_basename.setdefault(stem, []).append(path)
            self._by_segments[stem.lower()].append(path)
        self._by_path_lower: Dict[str, str] = {p.lower(): p for p in search_index.files}

    def _try_paths(self, candidates: Sequence[str]) -> Optional[str]:
        for c in candidates:
            norm = posixpath.normpath(c).lstrip("/")
            key = norm.lower()
            hit = self._by_path_lower.get(key)
            if hit is not None:
                return hit
            for suffix in ("/index",):
                pass
        return None

    def resolve(self, target: str, from_path: str, language: str) -> Optional[str]:
        """Return a repo-relative file path or None."""
        target = target.strip().strip('"').strip("'").lstrip("/")
        if not target:
            return None
        if target.startswith("."):  # relative import
            base_dir = posixpath.dirname(from_path)
            stem = posixpath.splitext(target)[0]
            candidates = [
                posixpath.join(base_dir, stem) + ext
                for ext in (".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".rs", ".go", ".java",
                            ".c", ".h", ".cc", ".cpp", ".hpp", ".rb", ".sh", ".rb", ".mod")
            ]
            if language in ("python",):
                candidates.append(posixpath.join(base_dir, stem, "__init__.py"))
            if language in ("javascript", "typescript"):
                candidates.append(posixpath.join(base_dir, target, "index.ts"))
                candidates.append(posixpath.join(base_dir, target, "index.js"))
            return self._try_paths(candidates)

        if language == "python":
            parts = target.split(".") if "." in target else [target]
            # last part is the module/file name
            stem = parts[-1].lower().replace("_", "")
            candidates = []
            for path in self._by_segments.get(stem, []):
                if path.endswith("__init__.py"):
                    candidates.append(path)
            for path in self._by_segments.get(stem, []):
                if not path.endswith("__init__.py"):
                    candidates.append(path)
            # dir import: package name = directory containing __init__.py
            for cand in candidates:
                if posixpath.basename(cand) == "__init__.py" and posixpath.basename(posixpath.dirname(cand)).lower() == stem:
                    return cand
            return candidates[0] if candidates else None

        if language in ("javascript", "typescript"):
            # bare specifiers (the "from 'pkg'") — match a top-level dir or a file whose stem matches the last segment
            stem = target.split("/")[-1].lower()
            candidates = self._by_segments.get(stem, [])
            for cand in candidates:
                if cand.endswith((".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")):
                    return cand
            return None

        if language == "java":
            # import com.acme.pkg.Thing → com/acme/pkg/Thing.java
            as_path = target.replace(".", "/") + ".java"
            return self._try_paths([as_path])

        if language == "rust":
            parts = target.split("::")
            if not parts:
                return None
            stem = parts[-1].lower()
            candidates = self._by_segments.get(stem, [])
            for cand in candidates:
                if cand.endswith(".rs"):
                    return cand
            return None

        if language in ("c", "cpp"):
            stem = os.path.splitext(os.path.basename(target))[0]
            candidates = self._by_segments.get(stem.lower(), [])
            for cand in candidates:
                if cand.endswith((".h", ".hpp", ".c", ".cc", ".cpp")):
                    return cand
            return None

        if language == "go":
            stem = target.split("/")[-1]
            for path in self._by_segments.get(stem.lower(), []):
                return path
            return None

        if language == "ruby":
            stem = target.replace("/", "_").lower()
            for path in self._by_segments.get(stem, []):
                if path.endswith(".rb"):
                    return path
            return None

        return None


class IndexBuilder:
    """Walks a repository and produces the full index dict."""

    def __init__(
        self,
        repo_root: str,
        config: Optional[Dict[str, Any]] = None,
        progress: Optional[Callable[[str], None]] = None,
    ):
        self.repo_root = os.path.abspath(repo_root)
        self.config = config or {}
        self.progress = progress or (lambda msg: None)
        self.graph = KnowledgeGraph()
        self.search_index = SearchIndex()
        self.summary: Dict[str, Any] = {}
        self._symbol_declarations: Dict[str, List[symbols.Symbol]] = defaultdict(list)
        self._decl_locations: Dict[str, List[Tuple[str, int]]] = defaultdict(list)
        self._extraction: Dict[str, Tuple[str, List[Any], symbols.ExtractionResult, str]] = {}
        self._last_lines = 0

    # -- main ---------------------------------------------------------------

    def build(self) -> Dict[str, Any]:
        t0 = time.time()
        self.progress("scanning repository…")
        ignore = IncrementalIgnore(
            self.repo_root,
            extra_patterns=self.config.get("ignore_patterns") or [],
        )
        respect = bool(self.config.get("respect_gitignore", True))
        include_hidden = bool(self.config.get("include_hidden", False))
        max_depth = int(self.config.get("index_depth", 12))
        max_bytes = int(self.config.get("max_file_bytes", 1_000_000))
        lang_filter = None
        if self.config.get("languages") not in (None, "auto"):
            lang_filter = set(languages.filter_languages(self.config["languages"]))

        lang_counter: Counter = Counter()
        total_lines = 0
        total_bytes = 0
        skipped = Counter()

        for dirpath, dirnames, filenames in os.walk(self.repo_root, topdown=True):
            rel_dir = util.repo_relative(dirpath, self.repo_root)
            depth = 0 if rel_dir == "." else rel_dir.count("/") + 1
            if depth > max_depth:
                dirnames[:] = []
                continue

            # prune ignored / hidden directories
            kept: List[str] = []
            for d in sorted(dirnames):
                if d in (".git", ".hg", ".svn", ".bzr"):
                    continue
                if d.startswith(".") and not include_hidden:
                    continue
                rel_d = rel_dir + "/" + d if rel_dir != "." else d
                if respect and ignore.ignored(rel_d, is_dir=True):
                    continue
                kept.append(d)
            dirnames[:] = kept

            for fname in sorted(filenames):
                path = os.path.join(dirpath, fname)
                rel = util.repo_relative(path, self.repo_root)
                if fname.startswith(".") and not include_hidden:
                    skipped["hidden"] += 1
                    continue
                if respect and ignore.ignored(rel, is_dir=False):
                    skipped["gitignored"] += 1
                    continue
                try:
                    size = os.path.getsize(path)
                except OSError:
                    continue
                if size > max_bytes:
                    skipped["too_large"] += 1
                    continue
                lang = languages.language_for_path(rel) or "text"
                if lang_filter is not None and lang not in lang_filter:
                    skipped["filtered"] += 1
                    continue
                if not util.is_binary(path):
                    self._index_file(path, rel, lang, size)
                    lang_counter[lang] += 1
                    total_lines += self._last_lines
                    total_bytes += size
                else:
                    skipped["binary"] += 1

        self.progress("resolving imports…")
        self._resolve_imports()
        self.progress("finding cross-file references…")
        self._collect_references()
        self.search_index.finalize()

        root_name = os.path.basename(self.repo_root) or "repo"
        summary = {
            "files": len(self.search_index),
            "lines": total_lines,
            "bytes": total_bytes,
            "symbols": self.search_index.symbol_count(),
            "edges": len(self.graph.edges),
            "languages": dict(sorted(lang_counter.items(), key=lambda kv: -kv[1])),
            "skipped": dict(skipped),
            "duration_ms": int((time.time() - t0) * 1000),
        }
        self.summary = summary
        return self.to_dict(root_name)

    def _index_file(self, path: str, rel: str, lang: str, size: int) -> None:
        try:
            text = util.read_text_file(path)
        except OSError:
            return
        lines = text.count("\n") + (1 if text and not text.endswith("\n") else 0)

        token_list = lexer.tokenize(text, lang)
        significant = lexer.significant_tokens(token_list)
        code_tokens = len(significant)
        stats = lexer.token_stats(token_list)

        extraction = symbols.extract(text, lang)

        # term frequency from raw text words (cheap, no need for tokens)
        words = util.split_words(text)
        terms: Dict[str, int] = {}
        for w in words:
            terms[w] = terms.get(w, 0) + 1

        sym_hits: List[SymbolHit] = []
        fid = file_id(rel)
        self.graph.add_node(
            fid,
            "file",
            {
                "name": rel,
                "path": rel,
                "language": lang,
                "size": size,
                "lines": lines,
                "code_tokens": code_tokens,
                "mtime": int(os.path.getmtime(path)),
            },
        )
        for sym in extraction.symbols:
            sid = symbol_id(rel, sym.name, sym.line)
            self.graph.add_node(
                sid,
                "symbol",
                {
                    "name": sym.name,
                    "kind": sym.kind,
                    "path": rel,
                    "line": sym.line,
                    "col": sym.col,
                    "signature": sym.signature,
                    "doc": sym.doc,
                    "language": lang,
                },
            )
            self.graph.add_edge(fid, sid, EDGE_DEFINE)
            if sym.parent:
                parent_id = symbol_id(rel, sym.parent, sym.line)
                if self.graph.has_node(parent_id):
                    self.graph.add_edge(parent_id, sid, EDGE_CONTAINS)
            self._symbol_declarations[sym.name].append(sym)
            self._decl_locations[sym.name].append((rel, sym.line))
            sym_hits.append(
                SymbolHit(sym.name, rel, sym.line, sym.col, sym.kind, sym.signature, sym.doc)
            )

        self.search_index.add_file(
            FileEntry(
                path=rel,
                language=lang,
                size=size,
                lines=lines,
                code_tokens=code_tokens,
                symbols=sym_hits,
                terms=terms,
            )
        )
        self._last_lines = lines

        # stash extraction for reference pass
        self._extraction[rel] = (text, significant, extraction, lang)

    def _resolve_imports(self) -> None:
        resolver = ImportResolver(self.search_index)
        for path, (text, significant, extraction, lang) in list(self._extraction.items()):
            fid = file_id(path)
            for imp in extraction.imports:
                target = imp.target
                # `from mod import name` resolves against the *module*
                if lang == "python" and imp.source.startswith("from "):
                    m = re.search(r"^from (\S+) import", imp.source)
                    if m:
                        target = m.group(1)
                target_path = resolver.resolve(target, path, lang)
                if target_path and target_path != path and target_path in self.search_index.files:
                    self.graph.add_edge(fid, file_id(target_path), EDGE_IMPORT, {"target": imp.target})

    def _collect_references(self) -> None:
        """ident(` patterns referencing symbols declared in other files."""
        declared = self.search_index.symbol_names
        budget = int(self.config.get("max_ref_edges", 40_000))
        used = 0
        for path, (text, significant, extraction, lang) in self._extraction.items():
            fid = file_id(path)
            seen: Set[str] = set()
            tokens = significant
            for i, tok in enumerate(tokens):
                if tok.kind != "ident" or tok.value not in declared:
                    continue
                nxt = tokens[i + 1] if i + 1 < len(tokens) else None
                if not (nxt and nxt.kind == "punct" and nxt.value == "("):
                    continue
                # skip the file's own declaration lines
                if any(s.line == tok.line and s.name == tok.value for s in self._symbol_declarations[tok.value]):
                    continue
                for path, line in self._decl_locations[tok.value][:1]:
                    tid = symbol_id(path, tok.value, line)
                    if tid not in seen:
                        seen.add(tid)
                        self.graph.add_edge(fid, tid, EDGE_REF, {"name": tok.value})
                        used += 1
                        if used >= budget:
                            return

    def to_dict(self, root_name: str) -> Dict[str, Any]:
        return {
            "format_version": INDEX_FORMAT_VERSION,
            "created_at": int(time.time()),
            "root_name": root_name,
            "root_hash": util.short_hash(root_name, 8),
            "summary": self.summary,
            "search": self.search_index.to_dict(),
            "graph": self.graph.to_dict(),
        }


def build_index(repo_root: str, config: Optional[Dict[str, Any]] = None,
                progress: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    """One-shot convenience: build and return the index dict."""
    builder = IndexBuilder(repo_root, config, progress)
    return builder.build()


def load_index(store_dir: str) -> Dict[str, Any]:
    """Load ``index.json`` from a store, validating the format version."""
    from .config import store_paths

    path = store_paths(store_dir)["index"]
    data = util.read_json(path)
    if not isinstance(data, dict):
        raise StoreCorruptError(f"{path} is not a JSON object")
    version = data.get("format_version")
    if version != INDEX_FORMAT_VERSION:
        raise StoreCorruptError(
            f"index format version {version} != {INDEX_FORMAT_VERSION}; run `mnemodex index` to rebuild"
        )
    return data


def graph_from_index(index: Dict[str, Any]) -> KnowledgeGraph:
    return KnowledgeGraph.from_dict(index.get("graph", {}))


def search_from_index(index: Dict[str, Any]) -> SearchIndex:
    return SearchIndex.from_dict(index.get("search", {}))


def index_stats(index: Dict[str, Any]) -> Dict[str, Any]:
    return index.get("summary", {})