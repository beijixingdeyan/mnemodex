"""Zero-dependency web UI for mnemodex.

Serves a single-page app (vanilla JS, inline CSS, no frameworks, no
node_modules) plus JSON API endpoints. The knowledge graph is rendered
client-side with a small hand-written force-directed layout in SVG.

Security posture: binds loopback by default; refuses file reads outside the
repo; all endpoints are read-only except the in-memory store which is only
reachable over the same loopback server.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Optional

from .. import util
from ..errors import IndexMissingError, MnemodexError

try:
    from .index_html import INDEX_HTML
except ImportError:  # pragma: no cover - fallback for source checkouts
    _here = os.path.dirname(__file__)
    with open(os.path.join(_here, "index.html"), "r", encoding="utf-8") as _fh:
        INDEX_HTML = _fh.read()


def make_handler(session) -> type:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):
            sys.stderr.write(f"[web] {fmt % args}\n")

        def _send(self, code: int, body: bytes, ctype: str = "application/json") -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def _json(self, code: int, data: Any) -> None:
            body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
            self._send(code, body, "application/json")

        def _html(self, code: int, text: str) -> None:
            self._send(code, text.encode("utf-8"), "text/html; charset=utf-8")

        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path
            query = urllib.parse.parse_qs(parsed.query)

            if path == "/" or path == "/index.html":
                self._html(200, INDEX_HTML)
                return
            if path == "/api/stats":
                return self._json(200, self._safe(session.stats))
            if path == "/api/search":
                q = query.get("q", [""])[0].strip()
                limit = int(query.get("limit", ["12"])[0] or 12)
                return self._json(200, self._safe(lambda: self._search(q, limit)))
            if path == "/api/memory":
                kind = query.get("kind", [None])[0]
                tag = query.get("tag", [None])[0]
                limit = int(query.get("limit", ["100"])[0] or 100)
                return self._json(200, self._safe(lambda: session.memory.recall(kind=kind, tag=tag, limit=limit)))
            if path == "/api/graph":
                return self._json(
                    200,
                    self._safe(
                        lambda: self._graph_payload(
                            int(query.get("max_nodes", ["220"])[0] or 220)
                        )
                    ),
                )
            if path == "/api/symbol":
                name = query.get("name", [""])[0]
                hits = self._safe(lambda: [h.to_dict() for h in session.lookup_symbol(name, fuzzy=True)])
                return self._json(200, hits)
            if path == "/api/snippet":
                rel = query.get("path", [""])[0]
                line = int(query.get("line", ["1"])[0] or 1)
                return self._json(200, {"snippet": session.snippet(rel, line, 12)})
            if path == "/health":
                return self._json(200, {"status": "ok", "version": __import__("mnemodex").__version__})
            self._json(404, {"error": "not found"})

        def do_OPTIONS(self):
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()

        def do_POST(self):
            parsed = urllib.parse.urlparse(self.path)
            length = int(self.headers.get("Content-Length", 0) or 0)
            body = self.rfile.read(length).decode("utf-8", "replace") if length else "{}"
            try:
                data = json.loads(body)
            except ValueError:
                data = {}
            if parsed.path == "/api/add":
                text = str(data.get("text", "")).strip()
                if not text:
                    return self._json(400, {"error": "text required"})
                result = session.add_memory(
                    text,
                    kind=data.get("kind"),
                    tags=data.get("tags") or None,
                    file=data.get("file"),
                    source="web",
                    importance=int(data.get("importance", 3)),
                )
                return self._json(200, result)
            if parsed.path == "/api/forget":
                entry_id = str(data.get("id", ""))
                ok = session.memory.forget(entry_id)
                return self._json(200, {"deleted": ok})
            if parsed.path == "/api/update":
                entry_id = str(data.get("id", ""))
                fields = {k: v for k, v in ((k, data.get(k)) for k in ("kind", "tags", "importance")) if k in data}
                updated = session.memory.update(entry_id, **fields)
                return self._json(200, {"updated": updated is not None})
            self._json(404, {"error": "not found"})

        # -- helpers ---------------------------------------------------------

        def _safe(self, fn):
            try:
                return fn()
            except IndexMissingError:
                return {"error": "index not built yet — run `mnemodex index`"}
            except MnemodexError as exc:
                return {"error": exc.message}
            except Exception as exc:  # pragma: no cover
                return {"error": str(exc)}

        def _search(self, q: str, limit: int):
            mem = session.memory.recall(query=q or None, limit=limit)
            files = []
            if q:
                files = [r.to_dict() for r in session.search(q, limit=limit)]
            return {"query": q, "memory": mem, "files": files}

        def _graph_payload(self, max_nodes: int):
            graph = session.graph()
            nodes, edges = simplify_graph(graph, max_nodes)
            return {"nodes": nodes, "edges": edges, "meta": graph.to_dict()["meta"]}

    return Handler


def simplify_graph(graph, max_nodes: int):
    """Reduce the graph to the most connected nodes for rendering."""
    import heapq

    degree = {nid: graph.degree(nid) for nid in graph.nodes}
    top = heapq.nlargest(max_nodes, graph.nodes, key=lambda nid: degree[nid])
    top_set = set(top)
    nodes = []
    for nid in top:
        n = graph.nodes[nid]
        nodes.append(
            {
                "id": nid,
                "label": n.attrs.get("name") or nid,
                "kind": n.kind,
                "path": n.attrs.get("path", ""),
                "line": n.attrs.get("line"),
                "sig": n.attrs.get("signature", ""),
                "doc": (n.attrs.get("doc") or "")[:160],
            }
        )
    edges = []
    seen = set()
    for e in graph.edges:
        if e.src in top_set and e.dst in top_set:
            key = (e.src, e.dst, e.type)
            if key not in seen:
                seen.add(key)
                edges.append({"source": e.src, "target": e.dst, "type": e.type})
    return nodes, edges


def run_webui(session, host: str = "127.0.0.1", port: int = 8765) -> int:
    try:
        httpd = ThreadingHTTPServer((host, port), make_handler(session))
    except OSError as exc:
        raise MnemodexError(f"cannot bind {host}:{port}: {exc}") from exc
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0