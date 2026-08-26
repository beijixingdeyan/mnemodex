# mnemodex MCP server

`mnemodex serve` speaks the [Model Context Protocol](https://modelcontextprotocol.io)
(JSON-RPC 2.0) so any MCP-capable agent gets repo memory, code intelligence and
context packs over a pipe — no CLI parsing, no screen-scraping.

Protocol version: `2024-11-05` (see `mnemodex/version.py`).

## Transports

```sh
# stdio (default) — for Claude Desktop, Cursor, IDE agents, your own scripts:
mnemodex serve --transport stdio

# SSE (HTTP) — default http://127.0.0.1:8766 :
mnemodex serve --transport sse --host 127.0.0.1 --port 8766
```

The server discovers the store like the CLI does — the nearest ancestor containing
`.mnemodex/` from *its* working directory. Bots that start it in your repo root get
your repo's memory automatically.

## Client config examples

```jsonc
// Claude Desktop: claude_desktop_config.json
{
  "mcpServers": {
    "mnemodex": { "command": "mnemodex", "args": ["serve"] }
  }
}

// Cursor: ~/.cursor/mcp.json
{
  "mcpServers": {
    "mnemodex": { "command": "mnemodex", "args": ["serve"] }
  }
}
```

## Tools

| tool | what it does |
| --- | --- |
| `mnemodex_recall(query, kind?, tag?, limit?)` | memory ranked by relevance/relevancy/importance |
| `mnemodex_add(text, kind?, tags?, file?, line?, importance?)` | write a fact to memory |
| `mnemodex_context(query, budget?)` | assemble a token-budgeted context pack (memory → symbols → snippets → dependents) |
| `mnemodex_lookup_symbol(name)` | every definition of a symbol: file, line, signature, doc |
| `mnemodex_files(query?, language?, limit?)` | file search over the index |
| `mnemodex_read_file(path, start_line?, end_line?)` | safe, repo-relative file read (path-traversal guarded) |
| `mnemodex_forget(id)` / `(query)` | delete one entry or everything matching |
| `mnemodex_list_memory(kind?, tag?, limit?)` | browse the memory store |
| `mnemodex_stats()` | store + index statistics |
| `mnemodex_git(what)` | recent commits / touched files / hot files (requires git, degrades gracefully) |

All tool results are plain JSON-serializable dicts (see `mnemodex/mcp.py` for the
exact schemas). Errors return MCP error objects with stable codes:

```text
-32700 parse error           -32600 invalid request
-32601 method not found      -32602 invalid params
-32001 store not initialized -32002 index not found
```

## Specification surface

- `initialize` → server info `{name: "mnemodex", version: <semver>, protocolVersion}`
- `notifications/initialized`
- `tools/list` → the 10 tools above with input schemas
- `tools/call` → `{content: [{type: "text", text: <json>}], isError: false}`
- `ping`

Anything else is answered with `method not found` — the server is small and
deliberately boring. If a client sends garbage, it gets a parse error *and* the
server keeps running (never crashes the session).

## Privacy

- All tools operate on repo-relative paths; `read_file` rejects path traversal
  (`..`, absolute paths, symlink escapes).
- Memory entries store exactly what you write; keep repo-relative `file` refs.
- Nothing leaves the machine — no telemetry, no network calls.