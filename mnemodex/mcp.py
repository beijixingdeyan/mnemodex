"""A from-scratch Model Context Protocol (MCP) server.

Implements the MCP JSON-RPC 2.0 `2024-11-05` subset over two transports:

* **stdio** — the standard MCP transport; Claude Code, Cursor, Cline,
  Gemini CLI open `mnemodex serve` as a subprocess and speak JSON-RPC line
  framed over stdin/stdout. All diagnostics go to stderr.
* **SSE** — HTTP + Server-Sent-Events (`mnemodex serve --transport sse`),
  suitable for remote agents and for verifying the server with curl.

Zero dependencies: the JSON-RPC plumbing, framing and tool registry are all
implemented here against the Python standard library.

Tools (prefixed `mnemodex_`) let an agent:

    mnemodex_recall        search memory + index
    mnemodex_add           write durable memory
    mnemodex_context       ask for a compressed context pack
    mnemodex_lookup_symbol resolve a symbol to its defining files
    mnemodex_files         find files by query
    mnemodex_read_file     read a snippet (traversal-safe)
    mnemodex_forget        delete a memory entry
    mnemodex_stats         store stats
    mnemodex_git           git signals (commits / hot files)

Any other method gets a proper JSON-RPC error, so clients fail loudly
instead of silently.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from .errors import MnemodexError
from .version import MCP_PROTOCOL_VERSION, PRODUCT_NAME, PRODUCT_TAGLINE, __version__

JSON_RPC_VERSION = "2.0"

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
MCP_ERROR = -32000


class Tool:
    """A callable tool exposed over MCP."""

    __slots__ = ("name", "description", "input_schema", "handler")

    def __init__(
        self,
        name: str,
        description: str,
        input_schema: Dict[str, Any],
        handler: Callable[[Dict[str, Any]], Any],
    ):
        self.name = name
        self.description = description
        self.input_schema = input_schema
        self.handler = handler

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "description": self.description, "inputSchema": self.input_schema}


class McpServer:
    """JSON-RPC dispatch core (transport-agnostic)."""

    def __init__(self, tools: Optional[List[Tool]] = None, log: Optional[Callable[[str], None]] = None):
        self.tools: Dict[str, Tool] = {}
        self.log = log or (lambda msg: None)
        self.sessions: Dict[str, Dict[str, Any]] = {}
        if tools:
            for tool in tools:
                self.register(tool)

    def register(self, tool: Tool) -> None:
        self.tools[tool.name] = tool

    # -- dispatch ---------------------------------------------------------

    def handle_line(self, raw: str, session_id: Optional[str] = None) -> Optional[str]:
        """Handle one raw JSON-RPC message; returns a serialized response or None."""
        raw = raw.strip()
        if not raw:
            return None
        try:
            message = json.loads(raw)
        except ValueError:
            return json.dumps(
                self._error(None, PARSE_ERROR, "parse error", raw[:200]),
                ensure_ascii=False,
                separators=(",", ":"),
            )
        if not isinstance(message, dict):
            return self._error(None, INVALID_REQUEST, "request must be a JSON object")
        if message.get("jsonrpc") != JSON_RPC_VERSION:
            return self._error(message.get("id"), INVALID_REQUEST, "jsonrpc must be 2.0")
        response = self.dispatch(message, session_id)
        if response is None:
            return None  # notification
        return json.dumps(response, ensure_ascii=False, separators=(",", ":"))

    def dispatch(self, message: Dict[str, Any], session_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        method = message.get("method", "")
        msg_id = message.get("id")
        params = message.get("params") or {}

        if method == "initialize":
            self.sessions.setdefault(session_id or _new_session_id(), {})
            return self._result(
                msg_id,
                {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {"tools": {"listChanged": True}},
                    "serverInfo": {"name": PRODUCT_NAME, "version": __version__},
                    "instructions": (
                        f"{PRODUCT_TAGLINE} Use the mnemodex_* tools for repository memory "
                        "and codebase intelligence. Prefer mnemodex_context for compact "
                        "answers, mnemodex_lookup_symbol for definitions."
                    ),
                },
            )

        if method == "notifications/initialized":
            return None
        if method == "notifications/cancelled":
            return None
        if method == "ping":
            return self._result(msg_id, {})

        if method == "tools/list":
            return self._result(msg_id, {"tools": [t.to_dict() for t in self.tools.values()]})

        if method == "tools/call":
            tool_name = params.get("name")
            tool = self.tools.get(tool_name)
            if tool is None:
                return self._error(msg_id, METHOD_NOT_FOUND, f"unknown tool: {tool_name}")
            arguments = params.get("arguments") or {}
            if not isinstance(arguments, dict):
                return self._error(msg_id, INVALID_PARAMS, "arguments must be an object")
            try:
                result = tool.handler(arguments)
                if isinstance(result, dict) and result.get("_error"):
                    return self._error(msg_id, MCP_ERROR, str(result.get("_error")))
                return self._result(msg_id, _tool_result(result))
            except MnemodexError as exc:
                return self._error(msg_id, MCP_ERROR, exc.pretty())
            except Exception as exc:  # defensive
                self.log(f"tool {tool_name} raised: {exc!r}")
                return self._error(msg_id, INTERNAL_ERROR, f"tool {tool_name} failed: {exc}")

        if method == "resources/list":
            return self._result(msg_id, {"resources": []})
        if method == "prompts/list":
            return self._result(msg_id, {"prompts": []})

        return self._error(msg_id, METHOD_NOT_FOUND, f"method not found: {method}")

    # -- json-rpc helpers -------------------------------------------------

    def _result(self, msg_id: Any, result: Any) -> Dict[str, Any]:
        return {"jsonrpc": JSON_RPC_VERSION, "id": msg_id, "result": result}

    def _error(self, msg_id: Any, code: int, message: str, data: Any = None) -> Dict[str, Any]:
        err: Dict[str, Any] = {"code": code, "message": message}
        if data is not None:
            err["data"] = str(data)[:2000]
        return {"jsonrpc": JSON_RPC_VERSION, "id": msg_id, "error": err}

    # -- transports ---------------------------------------------------------

    def serve_stdio(self) -> None:
        """Serve MCP over stdin/stdout until EOF. Never returns on success."""
        self.log("mnemodex MCP server (stdio) ready")
        for line in sys.stdin:
            if not line:
                break
            try:
                response = self.handle_line(line)
            except Exception as exc:  # defensive: keep the stream alive
                response = self._error(None, INTERNAL_ERROR, f"internal error: {exc}")
            if response is not None:
                sys.stdout.write(response + "\n")
                sys.stdout.flush()

    def serve_sse(self, host: str = "127.0.0.1", port: int = 8766) -> None:
        """Serve MCP over SSE on an HTTP server (blocks forever)."""
        httpd = ThreadingHTTPServer((host, port), _make_sse_handler(self))
        self.log(f"mnemodex MCP SSE server on http://{host}:{port} (GET /sse)")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            httpd.server_close()


# ---------------------------------------------------------------------------
# SSE transport
# ---------------------------------------------------------------------------

class _SSEConnection:
    def __init__(self):
        self.queue: "queue.Queue[str]" = __import__("queue").Queue()
        self.open = True


def _make_sse_handler(server: McpServer):
    connections: Dict[str, _SSEConnection] = {}

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):  # silence request spam to stderr
            pass

        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path == "/sse":
                session_id = parse_qs(parsed.query).get("session_id", [None])[0] or _new_session_id()
                conn = _SSEConnection()
                connections[session_id] = conn
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "keep-alive")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                try:
                    self.wfile.write(
                        f"event: endpoint\ndata: /messages?session_id={session_id}\n\n".encode()
                    )
                    self.wfile.flush()
                    while conn.open:
                        try:
                            payload = conn.queue.get(timeout=15)
                            self.wfile.write(f"event: message\ndata: {payload}\n\n".encode())
                            self.wfile.flush()
                        except Exception:
                            pass
                except (BrokenPipeError, ConnectionResetError):
                    pass
                finally:
                    conn.open = False
                    connections.pop(session_id, None)
                return
            elif parsed.path == "/health":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"status":"ok"}')
                return
            self.send_response(404)
            self.end_headers()

        def do_POST(self):
            parsed = urlparse(self.path)
            if parsed.path != "/messages":
                self.send_response(404)
                self.end_headers()
                return
            session_id = parse_qs(parsed.query).get("session_id", [None])[0]
            length = int(self.headers.get("Content-Length", 0) or 0)
            body = self.rfile.read(length).decode("utf-8", "replace") if length else ""
            conn = connections.get(session_id)
            response = server.handle_line(body, session_id)
            self.send_response(202)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(b"Accepted")
            if response is not None and conn is not None:
                conn.queue.put(response)

        def do_OPTIONS(self):
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()

    return Handler


def _new_session_id() -> str:
    return "%016x" % int(time.time() * 1_000_000 % (2**64))


def _tool_result(result: Any) -> Dict[str, Any]:
    """Wrap a tool return value as MCP content."""
    if isinstance(result, str):
        text = result
    else:
        text = json.dumps(result, ensure_ascii=False, indent=2)
    return {"content": [{"type": "text", "text": text}]}


# ---------------------------------------------------------------------------
# tool definitions bound to a Session
# ---------------------------------------------------------------------------

def build_tools(session) -> List[Tool]:
    """Assemble the tool registry for a mnemodex Session."""
    from .errors import IndexMissingError

    def _safe_index(fn: Callable[[], Any]) -> Any:
        try:
            return fn()
        except IndexMissingError:
            return {"_error": "index not built yet — run `mnemodex index` in the repository"}

    def recall(args: Dict[str, Any]) -> Any:
        query = str(args.get("query", "")).strip()
        limit = min(int(args.get("limit", 10)), 50)
        kind = args.get("kind")
        tag = args.get("tag")
        if query:
            memory_hits = [
                {k: e.get(k) for k in ("id", "kind", "text", "tags", "file", "line", "created_at", "importance")}
                for e in session.memory.recall(query=query, kind=kind, tag=tag, limit=limit)
            ]
            files = _safe_index(lambda: [r.to_dict() for r in session.search(query, limit=limit)])
        else:
            memory_hits = [
                {k: e.get(k) for k in ("id", "kind", "text", "tags", "file", "line", "created_at", "importance")}
                for e in session.memory.recall(kind=kind, tag=tag, limit=limit)
            ]
            files = []
        return {"memory": memory_hits, "files": files, "query": query}

    def add(args: Dict[str, Any]) -> Any:
        text = str(args.get("text", "")).strip()
        if not text:
            return {"_error": "`text` is required"}
        result = session.add_memory(
            text,
            kind=args.get("kind"),
            tags=args.get("tags") or [],
            file=args.get("file"),
            line=args.get("line"),
            source="mcp",
            importance=int(args.get("importance", 3)),
            ttl=args.get("ttl_days"),
        )
        return result

    def context(args: Dict[str, Any]) -> Any:
        query = str(args.get("query", "")).strip()
        budget = int(args.get("budget_tokens", 0) or 0) or None
        pack = session.context_pack(query, budget)
        return {"text": pack.render(), "sections": [s.get("title") for s in pack.sections], "tokens": pack.used}

    def lookup_symbol(args: Dict[str, Any]) -> Any:
        name = str(args.get("name", "")).strip()
        if not name:
            return {"_error": "`name` is required"}
        hits = session.lookup_symbol(name, fuzzy=bool(args.get("fuzzy", True)))
        return {"symbol": name, "hits": [h.to_dict() for h in hits]}

    def files(args: Dict[str, Any]) -> Any:
        query = str(args.get("query", "")).strip()
        limit = min(int(args.get("limit", 15)), 50)
        language = args.get("language")
        results = session.search(query, limit=limit, language=language)
        return {"files": [r.to_dict() for r in results]}

    def read_file(args: Dict[str, Any]) -> Any:
        path = str(args.get("path", ""))
        start = int(args.get("start_line", 1))
        span = min(int(args.get("span", 20)), 200)
        return {"snippet": session.snippet(path, start, span)}

    def forget(args: Dict[str, Any]) -> Any:
        entry_id = str(args.get("id", ""))
        if not entry_id:
            return {"_error": "`id` is required"}
        ok = session.memory.forget(entry_id)
        return {"deleted": ok, "id": entry_id}

    def list_memory(args: Dict[str, Any]) -> Any:
        limit = min(int(args.get("limit", 25)), 100)
        entries = session.memory.recall(kind=args.get("kind"), tag=args.get("tag"), limit=limit)
        return {"entries": [{k: e.get(k) for k in ("id", "kind", "text", "tags", "file", "line", "created_at")} for e in entries]}

    def stats(args: Dict[str, Any]) -> Any:
        return session.stats()

    def git(args: Dict[str, Any]) -> Any:
        return session.git_summary()

    tools = [
        Tool(
            "mnemodex_recall",
            "Search the repository's persistent memory (decisions, gotchas, tips, conventions, API notes) "
            "and the code index. Use before modifying code you haven't touched recently.",
            {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Free-text topic, e.g. 'auth caching'"}, 
                    "limit": {"type": "integer", "default": 10},
                    "kind": {"type": "string", "enum": list(__import__("mnemodex.store", fromlist=["KINDS"]).KINDS)},
                    "tag": {"type": "string"},
                },
                "required": ["query"],
            },
            recall,
        ),
        Tool(
            "mnemodex_add",
            "Write a durable memory entry: decisions, gotchas, conventions or API notes that future sessions "
            "should know. Always call this after learning something non-obvious.",
            {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "kind": {"type": "string", "enum": list(__import__("mnemodex.store", fromlist=["KINDS"]).KINDS)},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "file": {"type": "string", "description": "repo-relative path context"},
                    "line": {"type": "integer"},
                    "importance": {"type": "integer", "minimum": 1, "maximum": 5, "default": 3},
                    "ttl_days": {"type": "integer"},
                },
                "required": ["text"],
            },
            add,
        ),
        Tool(
            "mnemodex_context",
            "Return a token-budgeted context pack (memory + symbols + snippets + dependents) for a task. "
            "The fastest way to answer 'what do I need to know about X?'.",
            {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "budget_tokens": {"type": "integer", "default": 8000, "maximum": 128000},
                },
                "required": ["query"],
            },
            context,
        ),
        Tool(
            "mnemodex_lookup_symbol",
            "Resolve a symbol (function/class/struct name) to its defining files and signatures.",
            {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "fuzzy": {"type": "boolean", "default": True},
                },
                "required": ["name"],
            },
            lookup_symbol,
        ),
        Tool(
            "mnemodex_files",
            "Find source files relevant to a free-text query (deterministic TF-IDF + symbol match).",
            {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "default": 15},
                    "language": {"type": "string"},
                },
                "required": ["query"],
            },
            files,
        ),
        Tool(
            "mnemodex_read_file",
            "Read a repo-relative file snippet. Traversal-safe (refuses paths outside the repo).",
            {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "start_line": {"type": "integer", "default": 1},
                    "span": {"type": "integer", "default": 20},
                },
                "required": ["path"],
            },
            read_file,
        ),
        Tool(
            "mnemodex_forget",
            "Delete a memory entry by id.",
            {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
            forget,
        ),
        Tool(
            "mnemodex_list_memory",
            "List memory entries, optionally filtered by kind/tag.",
            {
                "type": "object",
                "properties": {
                    "kind": {"type": "string"},
                    "tag": {"type": "string"},
                    "limit": {"type": "integer", "default": 25},
                },
            },
            list_memory,
        ),
        Tool(
            "mnemodex_stats",
            "Repository + memory statistics for this mnemodex store.",
            {"type": "object", "properties": {}},
            stats,
        ),
        Tool(
            "mnemodex_git",
            "Git signals: current branch, recent commits, hot files. Fails gracefully without git.",
            {"type": "object", "properties": {}},
            git,
        ),
    ]
    return tools


def server_for_session(session) -> McpServer:
    """Build the MCP server wired to a Session."""
    return McpServer(build_tools(session))