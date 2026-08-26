"""Session: shared runtime state for CLI, MCP and web UI.

A Session discovers the store, loads configuration lazily, and exposes the
high-level operations every interface needs. Creating a Session raises
:class:`NotInitializedError` when no store is present — callers translate
that into their own UX (CLI error, MCP error response, web 404).
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Set

from . import config as config_mod
from . import gitlog, graph, indexer, search, util
from .errors import IndexMissingError, NotInitializedError
from .memory import Memory
from .store import KINDS


class Session:
    def __init__(self, cwd: Optional[str] = None, store_dir: Optional[str] = None):
        self.cwd = os.path.abspath(cwd or os.getcwd())
        if store_dir:
            self.store_dir = os.path.abspath(store_dir)
            if not os.path.isdir(self.store_dir):
                raise NotInitializedError(self.cwd)
        else:
            found = config_mod.discover_store(self.cwd)
            if found is None:
                raise NotInitializedError(self.cwd)
            self.store_dir = found
        self.config = config_mod.load_config(self.store_dir)
        self.repo_root = config_mod.repo_root_for_store(self.store_dir)
        self._index: Optional[Dict[str, Any]] = None
        self._memory: Optional[Memory] = None

    # -- cached accessors ----------------------------------------------------

    @property
    def memory(self) -> Memory:
        if self._memory is None:
            self._memory = Memory(self.store_dir, ttl_days=dict(self.config.get("ttl_days", {})))
        return self._memory

    def require_index(self) -> Dict[str, Any]:
        if self._index is None:
            path = os.path.join(self.store_dir, "index.json")
            if not os.path.exists(path):
                raise IndexMissingError()
            self._index = indexer.load_index(self.store_dir)
        return self._index

    def search_index(self) -> search.SearchIndex:
        return indexer.search_from_index(self.require_index())

    def graph(self) -> graph.KnowledgeGraph:
        return indexer.graph_from_index(self.require_index())

    def reload_index(self) -> None:
        self._index = None

    # -- high-level ops --------------------------------------------------------

    def search(
        self,
        query: str,
        limit: int = 10,
        language: Optional[str] = None,
        path_prefix: Optional[str] = None,
    ) -> List[search.SearchResult]:
        idx = self.search_index()
        return idx.search(query, limit=limit, language=language, path_prefix=path_prefix)

    def lookup_symbol(self, name: str, fuzzy: bool = False) -> List[search.SymbolHit]:
        return self.search_index().lookup_symbol(name, fuzzy=fuzzy)

    def context_pack(self, query: str, budget_tokens: Optional[int] = None) -> Any:
        from .compress import build_context

        budget = budget_tokens or int(self.config.get("compression_budget_tokens", 8000))
        mem = self.memory.recall(query=query, limit=12)
        return build_context(
            query,
            search_index=self.search_index(),
            memory_entries=mem,
            graph=self.graph(),
            repo_root=self.repo_root,
            budget_tokens=budget,
        )

    def add_memory(
        self,
        text: str,
        kind: Optional[str] = None,
        tags: Optional[List[str]] = None,
        file: Optional[str] = None,
        line: Optional[int] = None,
        source: str = "session",
        importance: int = 3,
        ttl: Optional[int] = None,
    ) -> Dict[str, Any]:
        return self.memory.add(
            text,
            kind=kind,
            tags=tags,
            file=file,
            line=line,
            source=source,
            importance=importance,
            ttl=ttl,
            auto_kind=bool(self.config.get("autocategorize", True)),
        )

    def git_summary(self) -> Dict[str, Any]:
        return gitlog.summarise(self.repo_root)

    def snippet(self, path: str, start_line: int = 1, span: int = 8) -> str:
        return indexer.read_snippet(self.repo_root, path, start_line, span)

    def stats(self) -> Dict[str, Any]:
        index_stats = {}
        try:
            data = self.require_index()
            index_stats = data.get("summary", {})
        except IndexMissingError:
            pass
        mem = self.memory.stats()
        return {"memory": mem, "index": index_stats, "version": __import__("mnemodex").__version__}


SESSION = None  # process-wide current session; set by cli/main