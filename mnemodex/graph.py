"""The mnemodex knowledge graph.

Node kinds
----------
* ``file``   — one indexed source file (id ``f:<path>``)
* ``symbol`` — one extracted declaration (id ``s:<path>:<name>@<line>``)
* ``module`` — a language-level module / package (Go package, Rust crate
  module, Java package, ...)

Edge types
----------
* ``import``   — file A imports file B (or a module)     (A → B)
* ``define``   — file defines a symbol                  (file → symbol)
* ``contains`` — symbol nested inside another symbol     (parent → child)
* ``ref``      — file references a symbol declared in file B (A → B)

The graph is what makes "which file does this symbol live in?" and "what
breaks if I change this function?" answerable without an embedding model.
"""

from __future__ import annotations

import re
from collections import defaultdict, deque
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence, Set, Tuple

from . import util

NODE_FILE = "file"
NODE_SYMBOL = "symbol"
NODE_MODULE = "module"

EDGE_IMPORT = "import"
EDGE_DEFINE = "define"
EDGE_CONTAINS = "contains"
EDGE_REF = "ref"


def file_id(path: str) -> str:
    return f"f:{path}"


def symbol_id(path: str, name: str, line: int) -> str:
    return f"s:{path}:{name}@{line}"


def module_id(path: str) -> str:
    return f"m:{path}"


class Node:
    __slots__ = ("id", "kind", "attrs")

    def __init__(self, id: str, kind: str, attrs: Optional[Dict[str, Any]] = None):
        self.id = id
        self.kind = kind
        self.attrs = dict(attrs or {})

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "kind": self.kind, **self.attrs}

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Node {self.kind}:{self.id}>"


class Edge:
    __slots__ = ("src", "dst", "type", "attrs")

    def __init__(self, src: str, dst: str, type: str, attrs: Optional[Dict[str, Any]] = None):
        self.src = src
        self.dst = dst
        self.type = type
        self.attrs = dict(attrs or {})

    def to_dict(self) -> Dict[str, Any]:
        return {"src": self.src, "dst": self.dst, "type": self.type, **self.attrs}

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Edge {self.type}: {self.src} → {self.dst}>"


class KnowledgeGraph:
    """In-memory knowledge graph with serialization and traversal helpers."""

    def __init__(self) -> None:
        self.nodes: Dict[str, Node] = {}
        self.edges: List[Edge] = []
        self._out: Dict[str, List[Edge]] = defaultdict(list)
        self._in: Dict[str, List[Edge]] = defaultdict(list)

    # -- mutation -----------------------------------------------------------

    def add_node(self, id: str, kind: str, attrs: Optional[Dict[str, Any]] = None) -> Node:
        node = self.nodes.get(id)
        if node is None:
            node = Node(id, kind, attrs)
            self.nodes[id] = node
        elif attrs:
            node.attrs.update(attrs)
        return node

    def add_edge(self, src: str, dst: str, type: str, attrs: Optional[Dict[str, Any]] = None) -> Edge:
        edge = Edge(src, dst, type, attrs)
        self.edges.append(edge)
        self._out[src].append(edge)
        self._in[dst].append(edge)
        return edge

    def add_edge_dedup(self, src: str, dst: str, type: str, attrs: Optional[Dict[str, Any]] = None) -> Edge:
        for existing in self._out.get(src, ()):
            if existing.dst == dst and existing.type == type:
                existing.attrs.update(attrs or {})
                return existing
        return self.add_edge(src, dst, type, attrs)

    # -- queries ------------------------------------------------------------

    def has_node(self, id: str) -> bool:
        return id in self.nodes

    def get(self, id: str) -> Optional[Node]:
        return self.nodes.get(id)

    def out_edges(self, id: str, type: Optional[str] = None) -> List[Edge]:
        edges = self._out.get(id, [])
        if type:
            edges = [e for e in edges if e.type == type]
        return edges

    def in_edges(self, id: str, type: Optional[str] = None) -> List[Edge]:
        edges = self._in.get(id, [])
        if type:
            edges = [e for e in edges if e.type == type]
        return edges

    def out_neighbors(self, id: str, type: Optional[str] = None) -> List[str]:
        return [e.dst for e in self.out_edges(id, type)]

    def in_neighbors(self, id: str, type: Optional[str] = None) -> List[str]:
        return [e.src for e in self.in_edges(id, type)]

    def degree(self, id: str) -> int:
        return len(self._out.get(id, ())) + len(self._in.get(id, ()))

    def symbols_of_file(self, path: str) -> List[Node]:
        fid = file_id(path)
        return [self.nodes[e.dst] for e in self._out.get(fid, ()) if e.type == EDGE_DEFINE and e.dst in self.nodes]

    def file_of_symbol(self, symbol_name: str) -> List[Node]:
        """All symbol nodes with this name (across files)."""
        out: List[Node] = []
        for node in self.nodes.values():
            if node.kind == NODE_SYMBOL and node.attrs.get("name") == symbol_name:
                out.append(node)
        return out

    def files(self) -> List[Node]:
        return [n for n in self.nodes.values() if n.kind == NODE_FILE]

    def symbols(self) -> List[Node]:
        return [n for n in self.nodes.values() if n.kind == NODE_SYMBOL]

    def symbol_names(self) -> Set[str]:
        return {n.attrs.get("name") for n in self.symbols() if n.attrs.get("name")}

    # -- algorithms ----------------------------------------------------------

    def connected_components(self) -> List[List[str]]:
        """Weakly connected components over all nodes."""
        seen: Set[str] = set()
        components: List[List[str]] = []
        for start in self.nodes:
            if start in seen:
                continue
            comp: List[str] = []
            queue = deque([start])
            seen.add(start)
            while queue:
                node = queue.popleft()
                comp.append(node)
                for nxt in self._neighbors(node):
                    if nxt not in seen:
                        seen.add(nxt)
                        queue.append(nxt)
            components.append(comp)
        return components

    def _neighbors(self, id: str) -> Iterator[str]:
        for e in self._out.get(id, ()):
            yield e.dst
        for e in self._in.get(id, ()):
            yield e.src

    def shortest_path(self, a: str, b: str) -> Optional[List[str]]:
        """BFS shortest path between two node ids (returns node id list)."""
        if a not in self.nodes or b not in self.nodes:
            return None
        if a == b:
            return [a]
        prev: Dict[str, Optional[str]] = {a: None}
        queue = deque([a])
        while queue:
            cur = queue.popleft()
            for nxt in self._neighbors(cur):
                if nxt in prev:
                    continue
                prev[nxt] = cur
                if nxt == b:
                    path: List[str] = []
                    node: Optional[str] = nxt
                    while node is not None:
                        path.append(node)
                        node = prev[node]
                    path.reverse()
                    return path
                queue.append(nxt)
        return None

    def k_hop(self, id: str, k: int = 1) -> Dict[str, int]:
        """Distances (hops <= k) from a node to every reachable node."""
        dist: Dict[str, int] = {id: 0}
        queue = deque([id])
        while queue:
            cur = queue.popleft()
            if dist[cur] >= k:
                continue
            for nxt in self._neighbors(cur):
                if nxt not in dist:
                    dist[nxt] = dist[cur] + 1
                    queue.append(nxt)
        return dist

    def page_rank(self, damping: float = 0.85, iterations: int = 30) -> Dict[str, float]:
        """Power-iteration PageRank over the whole node set."""
        n = len(self.nodes)
        if n == 0:
            return {}
        ids = list(self.nodes.keys())
        idx = {node_id: i for i, node_id in enumerate(ids)}
        out_deg = [len(self._out.get(node_id, ())) for node_id in ids]
        # build adjacency (dense enough for repo-scale graphs)
        adj: List[List[int]] = [[] for _ in range(n)]
        for edge in self.edges:
            si = idx.get(edge.src)
            di = idx.get(edge.dst)
            if si is not None and di is not None and si != di:
                adj[si].append(di)
        rank = [1.0 / n] * n
        base = (1.0 - damping) / n
        for _ in range(iterations):
            new_rank = [base] * n
            for i in range(n):
                if out_deg[i] == 0:
                    # dangling nodes spread their rank evenly
                    spread = damping * rank[i] / n
                    for j in range(n):
                        new_rank[j] += spread
                else:
                    share = damping * rank[i] / out_deg[i]
                    for j in adj[i]:
                        new_rank[j] += share
            rank = new_rank
        return {ids[i]: r for i, r in enumerate(rank)}

    def hub_score(self) -> Dict[str, float]:
        """Files ranked by how many other files import them (hubness)."""
        scores: Dict[str, float] = defaultdict(float)
        for edge in self.edges:
            if edge.type == EDGE_IMPORT and edge.src.startswith("f:") and edge.dst.startswith("f:"):
                scores[edge.dst] += 1.0
        return dict(scores)

    # -- serialization --------------------------------------------------------

    def to_dict(self, include_attrs: bool = True) -> Dict[str, Any]:
        nodes = [n.to_dict() if include_attrs else {"id": n.id, "kind": n.kind} for n in self.nodes.values()]
        edges = [e.to_dict() for e in self.edges]
        meta = {
            "node_count": len(self.nodes),
            "edge_count": len(self.edges),
            "file_count": sum(1 for n in self.nodes.values() if n.kind == NODE_FILE),
            "symbol_count": sum(1 for n in self.nodes.values() if n.kind == NODE_SYMBOL),
        }
        return {"meta": meta, "nodes": nodes, "edges": edges}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "KnowledgeGraph":
        graph = cls()
        for node in data.get("nodes", []):
            attrs = {k: v for k, v in node.items() if k not in ("id", "kind")}
            graph.add_node(node["id"], node["kind"], attrs)
        for edge in data.get("edges", []):
            attrs = {k: v for k, v in edge.items() if k not in ("src", "dst", "type")}
            graph.add_edge(edge["src"], edge["dst"], edge["type"], attrs)
        return graph

    # -- export formats -------------------------------------------------------

    def to_dot(self, focus_files: Optional[Sequence[str]] = None, max_nodes: int = 2000) -> str:
        """DOT source for graphviz — great for `mnemodex graph --format dot`."""
        lines = ["digraph mnemodex {"]
        lines.append('  graph [rankdir=LR, fontname="monospace", splines=true];')
        lines.append('  node [fontname="monospace", shape=box];')
        shown: Set[str] = set()
        for node in self.nodes.values():
            if focus_files and node.kind == NODE_SYMBOL:
                continue
            label = node.attrs.get("name") or node.id
            if node.kind == NODE_FILE:
                label = f"{label}"
                shape = "folder"
            elif node.kind == NODE_SYMBOL:
                shape = {"function": "ellipse", "class": "box3d", "struct": "component"}.get(
                    node.attrs.get("kind"), "note"
                )
            else:
                shape = "diamond"
            safe_id = util.safe_name(node.id)
            safe_label = label.replace('"', '\\"')
            lines.append(f'  "{safe_id}" [label="{safe_label}", shape={shape}];')
            shown.add(node.id)
            if len(shown) >= max_nodes:
                break
        for edge in self.edges:
            if edge.src in shown and edge.dst in shown:
                color = {"import": "#4c8bf5", "ref": "#f5a623", "define": "#7ed321", "contains": "#9013fe"}.get(
                    edge.type, "#666666"
                )
                lines.append(f'  "{util.safe_name(edge.src)}" -> "{util.safe_name(edge.dst)}" [color="{color}", label="{edge.type}"];')
        lines.append("}")
        return "\n".join(lines)


def collect_unique_types(graph: KnowledgeGraph) -> List[str]:
    seen: List[str] = []
    for edge in graph.edges:
        if edge.type not in seen:
            seen.append(edge.type)
    return seen