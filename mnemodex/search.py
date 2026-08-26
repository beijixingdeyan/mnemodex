"""Deterministic, dependency-free search over the repository index.

Mnemodex deliberately does *not* require an embedding model. Instead it uses
a classic, explainable ranking model:

    score(file, query) =
        Σ_terms  idf(term) * tf(term, file)          (content)
      + path_bonus(query, file.path)                  (path tokens)
      + symbol_bonus(query, file.symbols)             (declared names)
      + ngram_fuzzy(query, file)                      (typo tolerance)

Everything is deterministic: the same query returns the same results on the
same index on every machine — a property the "vibe-coded RAG" crowd can't
offer, and one that makes results auditable and unit-testable.
"""

from __future__ import annotations

import math
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from . import util


class SymbolHit:
    __slots__ = ("name", "path", "line", "col", "kind", "signature", "doc")

    def __init__(self, name: str, path: str, line: int, col: int, kind: str, signature: str, doc: str):
        self.name = name
        self.path = path
        self.line = line
        self.col = col
        self.kind = kind
        self.signature = signature
        self.doc = doc

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "path": self.path,
            "line": self.line,
            "col": self.col,
            "kind": self.kind,
            "signature": self.signature,
            "doc": self.doc[:160],
        }


class FileEntry:
    __slots__ = ("path", "language", "size", "lines", "code_tokens", "symbols", "terms", "tf")

    def __init__(
        self,
        path: str,
        language: str,
        size: int,
        lines: int,
        code_tokens: int,
        symbols: List[SymbolHit],
        terms: Optional[Dict[str, int]] = None,
    ):
        self.path = path
        self.language = language
        self.size = size
        self.lines = lines
        self.code_tokens = code_tokens
        self.symbols = symbols
        self.terms: Dict[str, int] = terms or {}
        total = sum(self.terms.values()) or 1
        self.tf = {w: c / total for w, c in self.terms.items()}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "language": self.language,
            "size": self.size,
            "lines": self.lines,
            "code_tokens": self.code_tokens,
            "symbols": [s.to_dict() for s in self.symbols],
            "terms": self.terms,
        }


class SearchResult:
    __slots__ = ("path", "score", "reasons", "file", "matches")

    def __init__(self, path: str, score: float, reasons: Dict[str, float], file: Optional[FileEntry], matches: Tuple[str, ...]):
        self.path = path
        self.score = score
        self.reasons = reasons
        self.file = file
        self.matches = matches

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "score": round(self.score, 4),
            "reasons": {k: round(v, 4) for k, v in self.reasons.items()},
            "matches": list(self.matches),
            "symbols": [s.to_dict() for s in (self.file.symbols if self.file else [])][:12],
        }


class SearchIndex:
    """The in-memory search index; serialize/restore via :class:`IndexStore`."""

    def __init__(self) -> None:
        self.files: Dict[str, FileEntry] = {}
        self.df: Dict[str, int] = {}
        self.symbol_names: Set[str] = set()
        self._symbol_lookup: Dict[str, List[SymbolHit]] = {}
        self.idf: Dict[str, float] = {}

    # -- build ---------------------------------------------------------------

    def add_file(self, entry: FileEntry) -> None:
        self.files[entry.path] = entry
        for word in entry.terms:
            self.df[word] = self.df.get(word, 0) + 1
        for sym in entry.symbols:
            self.symbol_names.add(sym.name)
            self._symbol_lookup.setdefault(sym.name, []).append(sym)

    def finalize(self) -> None:
        n = len(self.files)
        self.idf = {
            word: math.log(1.0 + n / (1.0 + doc_count))
            for word, doc_count in self.df.items()
        }

    # -- counts --------------------------------------------------------------

    def __len__(self) -> int:
        return len(self.files)

    @property
    def document_frequency(self) -> int:
        return len(self.df)

    @property
    def unique_terms(self) -> int:
        return len(self.df)

    # -- symbol lookup -------------------------------------------------------

    def lookup_symbol(self, name: str, fuzzy: bool = False) -> List[SymbolHit]:
        exact = self._symbol_lookup.get(name)
        if exact or not fuzzy:
            return exact or []
        # prefix/contains fallback
        out: List[SymbolHit] = []
        low = name.lower()
        for sym_name, hits in self._symbol_lookup.items():
            if len(out) >= 20:
                break
            if sym_name.lower() == low:
                out.extend(hits)
            elif sym_name.lower().startswith(low) or low in sym_name.lower():
                out.extend(hits[:6])
        return out[:40]

    def symbol_count(self) -> int:
        return len(self.symbol_names)

    # -- query ---------------------------------------------------------------

    def search(
        self,
        query: str,
        limit: int = 10,
        *,
        language: Optional[str] = None,
        path_prefix: Optional[str] = None,
        include_paths: Optional[Set[str]] = None,
        max_ngram_scan: int = 400,
    ) -> List[SearchResult]:
        """Rank files against a free-text query."""
        words = util.split_words(query)
        if not words:
            return self._noop_results(limit)
        word_set = set(words)
        ngrams = set(util.ngrams(words, 3))

        results: List[SearchResult] = []
        scanned = 0
        for path, entry in self.files.items():
            if language and entry.language != language:
                continue
            if path_prefix and not (path == path_prefix or path.startswith(path_prefix + "/")):
                continue
            if include_paths is not None and path not in include_paths:
                continue
            scanned += 1
            score = 0.0
            reasons: Dict[str, float] = {}

            # 1. content tf-idf
            if word_set:
                content = 0.0
                for word in word_set:
                    tf = entry.tf.get(word)
                    if tf:
                        content += self.idf.get(word, 0.0) * tf
                if content:
                    reasons["content"] = content
                    score += content * 1.0

            # 2. path tokens (exact + substrings)
            path_low = path.lower().replace("\\", "/")
            path_bonus = 0.0
            for word in words:
                if word in path_low:
                    path_bonus += 1.2
                if "/" + word + "/" in "/" + path_low + "/":
                    path_bonus += 0.6
            if path_bonus:
                reasons["path"] = path_bonus
                score += path_bonus

            # 3. symbol match (declared names in this file)
            sym_bonus = 0.0
            for sym in entry.symbols:
                low_sym = sym.name.lower()
                if low_sym in word_set or any(w in low_sym for w in words):
                    sym_bonus += 2.5
                    break
            if sym_bonus:
                reasons["symbol"] = sym_bonus
                score += sym_bonus

            # 4. fuzzy n-gram overlap (typography tolerance), sampled
            if scanned <= max_ngram_scan and ngrams:
                terms_words = set()
                for w in entry.terms:
                    terms_words.update(util.split_words(w) or (w,))
                joined = "".join(terms_words)
                own = set(util.ngrams(terms_words, 3)) if terms_words else set()
                overlap = len(ngrams & own)
                if overlap:
                    fuzzy = overlap * 0.4
                    reasons["fuzzy"] = fuzzy
                    score += fuzzy

            if score > 0:
                results.append(SearchResult(path, score, reasons, entry, tuple(sorted(word_set))))

        results.sort(key=lambda r: (-r.score, r.path))
        return results[:limit]

    def search_symbols(self, query: str, limit: int = 15) -> List[SymbolHit]:
        """Rank *symbols* (not files) against a query."""
        words = util.split_words(query)
        scored: List[Tuple[float, SymbolHit]] = []
        for name, hits in self._symbol_lookup.items():
            low = name.lower()
            s = 0.0
            for w in words:
                if w in low:
                    s += 3.0
                    if low.startswith(w):
                        s += 1.0
                if any(w in p.lower() for h in hits for p in []):
                    pass
            # path scoring
            for h in hits[:3]:
                p = h.path.lower()
                for w in words:
                    if w in p:
                        s += 0.8
            if s > 0:
                for h in hits:
                    scored.append((s, h))
        scored.sort(key=lambda t: (-t[0], t[1].path))
        return [h for _, h in scored[:limit]]

    # -- helpers -------------------------------------------------------------

    def _noop_results(self, limit: int) -> List[SearchResult]:
        return [
            SearchResult(path, 0.0, {}, entry, ())
            for path, entry in list(self.files.items())[:limit]
        ]

    def stats(self) -> Dict[str, Any]:
        return {
            "files": len(self.files),
            "unique_terms": len(self.df),
            "symbols": self.symbol_count(),
            "total_terms": sum(len(e.terms) for e in self.files.values()),
        }

    # -- serialization -------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        files = [e.to_dict() for e in self.files.values()]
        return {"files": files}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SearchIndex":
        idx = cls()
        for raw in data.get("files", []):
            symbols = [
                SymbolHit(s["name"], s["path"], s["line"], s["col"], s["kind"], s.get("signature", ""), s.get("doc", ""))
                for s in raw.get("symbols", [])
            ]
            idx.add_file(
                FileEntry(
                    raw["path"],
                    raw.get("language", ""),
                    raw.get("size", 0),
                    raw.get("lines", 0),
                    raw.get("code_tokens", 0),
                    symbols,
                    raw.get("terms"),
                )
            )
        idx.finalize()
        return idx