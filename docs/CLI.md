# mnemodex CLI reference

`mnemodex` is a single zero-dependency Python command. Everything below is generated
against the code in this repository; run `mnemodex <command> --help` for the live
copy.

Global flags (before the subcommand):

```
--version                 print "mnemodex x.y.z" and exit
--cwd DIR                 run as if started in DIR
--log-level LEVEL         debug|info|warn|error|quiet (default: info)
--log-file FILE           append logs to FILE
```

Every command runs in the current directory (or `--cwd`) and discovers the store by
walking up: the **store root** is the nearest ancestor containing `.mnemodex/`.
Commands that need the store report `not initialized` and suggest `mnemodex init`
when they can't find one.

---

## `mnemodex init`

Create the store for this repository.

```
mnemodex init [--force] [--no-gitignore] [--example]
```

- Creates `.mnemodex/` with `config.json`, `memory.jsonl` and a placeholder index.
- Appends `.mnemodex/` to the repo `.gitignore` unless `--no-gitignore` (memory is
  local, not committed).
- `--example` seeds four memory entries (one per common kind) so you can try
  `mnemodex recall` immediately.
- `--force` recreates an existing store (data loss — it moves the old store aside).

## `mnemodex index`

Build/refresh the code index and knowledge graph.

```
mnemodex index [--config FILE]
```

Walks the repo (respecting `.gitignore`, hidden files, depth and size limits),
extracts symbols for 19 languages, resolves imports, collects cross-file references
and writes `index.json` plus the graph. `--config` points at a JSON file with
indexer options, e.g. `{"max_depth": 4, "max_bytes": 262144}`. Idempotent and
deterministic: same repo ⇒ same index bytes.

## `mnemodex add` — remember a fact

```
mnemodex add TEXT... [--file FILE] [--kind KIND] [--tags a,b] [--importance 1-5]
              [--ttl DAYS] [--ref PATH] [--line N] [--no-autocategorize]
```

Kinds: `decision`, `gotcha`, `tip`, `api`, `convention`, `task`, `note`.
Unless `--kind` is given (or `--no-autocategorize`), the kind is auto-detected from
wording. `--ref` attaches the fact to a repo-relative path (shown in `recall`).
`--importance` is 1–5 (default 3) and participates in ranking; `--ttl` expires the
entry after N days. Duplicate-ish entries (same token fingerprint) are merged.

```
mnemodex add "tokens expire after 60s; never cache the refresh token" --kind gotcha --tags cache,security
```

## `mnemodex recall` / `mnemodex ask` — find what matters

```
mnemodex recall QUERY... [--kind KIND] [--tag TAG] [--limit N] [--json]
mnemodex ask QUERY... [--budget N] [--json]
```

`recall` ranks memory entries by relevance (token overlap + substring fallback),
recency and importance. `ask` is `recall` plus code-index results and graph
neighbours, then packages everything into a **context pack**: memory → symbols →
snippets → dependents → largest files, capped at `--budget` tokens (default: pack a
sensible ~8k). `--json` emits structured output for scripts.

## `mnemodex search`

Full-text + fuzzy search over the indexed code.

```
mnemodex search QUERY... [--limit N] [--language LANG] [--path PREFIX] [--json]
```

TF-IDF with path/symbol bonuses plus n-gram fuzz for misspellings
(`mnemodex search cache eviction` finds `cached`, `evict`, `eviction_policy`).

## `mnemodex symbol`

Resolve a symbol name to its definitions across files.

```
mnemodex symbol NAME [--json]
```

Prints kind, file, line, signature and (where available) docstring for every
definition — the fastest way to answer "where is LRUCache and what does it look
like?".

## `mnemodex graph`

Inspect the knowledge graph.

```
mnemodex graph [--format json|dot|text] [--path NODE] [--path-a NODE] [--path-b NODE]
               [--hops N] [--components] [--out FILE]
```

- `--format dot'`/`--out` export Graphviz DOT for rendering.
- `--path-a A --path-b B` prints the shortest path between two nodes.
- `--path NODE --hops N` prints the N-hop neighbourhood.
- `--components` lists connected components.
- Node ids are `f:<path>` for files and `s:<path>:<name>@<line>` for symbols.

## `mnemodex serve` — MCP server

```
mnemodex serve [--transport stdio|sse] [--host HOST] [--port PORT]
```

JSON-RPC 2.0 MCP server exposing 10 tools: `mnemodex_recall`, `mnemodex_add`,
`mnemodex_context`, `mnemodex_lookup_symbol`, `mnemodex_files`, `mnemodex_read_file`,
`mnemodex_forget`, `mnemodex_list_memory`, `mnemodex_stats`, `mnemodex_git`.
`stdio` (default) speaks framed JSON on stdin/stdout — point Claude Desktop, Cursor,
vs-code agents or your own scripts at it. `sse` serves an HTTP SSE endpoint (default
`127.0.0.1:8766`). See `docs/MCP.md`.

## `mnemodex web`

Zero-dependency web UI (search, memory, force-directed graph, add/forget).

```
mnemodex web [--host HOST] [--port PORT] [--no-browser]
```

Default `http://127.0.0.1:8765`. Serves a vanilla-JS SPA from `mnemodex/webui/` over a
small JSON API (`/api/stats`, `/api/search`, `/api/memory`, `/api/graph`,
`/api/symbol`, `/api/snippet`, `/api/add`, `/api/forget`, `/api/update`).

## `mnemodex export`

Export memory, agent files or index summary.

```
mnemodex export memory [--format md|json] [--out FILE] [--kind K] [--tag T]
mnemodex export agent  [--targets claude,codex,cursor] [--dry-run]
mnemodex export index  [--out FILE]
```

`export agent` writes `CLAUDE.md`, `AGENTS.md` and/or `docs/cursor_rules.mdc` so
agents that don't speak MCP get the memory loop wired in via their file-based
convention. `export memory --format md` produces a shareable team-memory document.

## `mnemodex forget`

Delete memory entries.

```
mnemodex forget [ID] [--query TEXT]
```

By id, or everything matching a query (`--query`) — with a confirmation unless
`--yes` is given.

## `mnemodex list`

List memory entries.

```
mnemodex list [--kind KIND] [--tag TAG] [--limit N]
```

## `mnemodex stats`

Store statistics (counts per kind, index summary, disk bytes).

```
mnemodex stats [--json]
```

## `mnemodex doctor`

Diagnose the environment: Python version, store health, index freshness, git
availability, optional-missing modules (e.g. `numpy` if you ask for embeddings).
Exit code is non-zero when something needs fixing — useful in CI.

## `mnemodex gc`

Compaction: expire TTL'd entries, merge duplicates (same fingerprint), enforce the
hard cap. Reports `kept / expired / deduped`. `--quiet` prints nothing on success.

## `mnemodex gif`

Render the README demo GIF with the built-in GIF89a encoder:

```
mnemodex gif --out docs/demo.gif [--frames N] [--width W] [--height H]
```

Yes, this tool ships its own LZW GIF writer — zero dependencies means zero escape
hatches. See `docs/GIF_SPEC.md`.

## `mnemodex completion`

Emit shell completions for `bash`, `zsh`, `fish` or `powershell`:

```
mnemodex completion bash   # append to ~/.bashrc
mnemodex completion zsh    # append to ~/.zshrc
```

## Exit codes

| code | meaning |
| --- | --- |
| 0 | success |
| 1 | command failed (message on stderr) |
| 2 | usage error (argparse) |
| 3 | store missing / not initialized |
| 4 | index missing or stale (asked to search/symbol before `index`) |
| 5 | store corrupt (bad JSON, wrong format version) |

`mnemodex doctor` exits 1 when any check fails, 0 when all pass.