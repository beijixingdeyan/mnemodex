# Architecture

mnemodex is a single pure-Python package with **zero third-party dependencies**.
This document describes the data model, the pipeline and the reasoning behind the
layout. Reading time: ~10 minutes.

## Store layout

Everything lives in `.mnemodex/` at the store root (the nearest ancestor of the
current directory that contains it). The directory is appended to `.gitignore` at
`init` — memory is local to a machine/agent, not committed.

```text
.mnemodex/
├── config.json     # store settings: kind defaults, hard caps, web host/port
├── memory.jsonl    # append-only JSONL of memory entries (the "scars")
├── index.json      # search index + knowledge graph + summary, format v1
└── *.lock          # O_EXCL lock files for concurrent writers
```

All files are plain, diffable, human-readable JSON/JSONL. There is no database —
the cost of "just read it" is deliberate: it keeps the tool grep-able, backup-able
and crash-safe (every write is write-temp + fsync + atomic `os.replace`).

## Pipeline: from repo files to index

```text
repo files
   │  os.walk, .gitignore-aware (ReproIgnore matcher), hidden/depth/size pruning
   ▼
language_for_path  ──► 19 languages: python js ts rust c cpp java go ruby shell
   │                       json yaml toml markdown html css sql dockerfile makefile
   ▼
lexer (mnemodex/lexer.py)
   │  hand-rolled tokenizer: line/block/nested comments, docstrings, triple quotes,
   │  template strings, unicode identifiers; NEVER raises; emits (kind, value, line, col)
   ▼
symbols (mnemodex/symbols.py)
   │  per-language extractors -> Symbol(name, kind, line, col, signature, doc, parent)
   │  + Import(target, source, line)
   ▼
indexer (mnemodex/indexer.py)
   │  1. terms: TF-IDF (deterministic, no embeddings) + n-gram fuzzy index
   │  2. graph nodes: file / symbol; edges: import / define / ref / contains
   │  3. ImportResolver maps `from a.b import C` -> a/b.py etc.
   ▼
.mnemodex/index.json
```

### The lexer

`mnemodex/lexer.py` is a single-pass tokenizer with per-language config from
`mnemodex/languages.py`. Token kinds: `ident`, `keyword`, `string`, `number`,
`punct`, `comment`, `ws`, `unknown`. The lexer never fails: unparseable bytes
become `unknown` tokens rather than crashing an index run. Significant tokens
(dropping comments/whitespace) feed the extractors; raw tokens feed docstring and
`meta` heuristics.

### Symbol extraction

One extractor per language family (`extract_python`, `extract_javascript`,
`extract_rust`, `extract_c_family` for C/C++/Java, `extract_go`, `extract_ruby`,
`extract_shell`, `extract_markdown`). Key design points:

- Extractors are **state machines over significant tokens** with a `_Cursor`
  (peek/next/eat-balanced/restore). Guarantees: every loop advances or restores;
  no parser can hang.
- Call-site noise (a `foo(` that is a call, not a declaration) is filtered with
  lookalike guards: an ident followed by `(` whose previous token is a keyword
  like `return`/`new`/`if` is skipped, and `Type name(` in Java is treated as a
  call site.
- Docstrings/comments attached lazily by scanning a few tokens back from a
  declaration — cheap and good enough for context packs.

## Memory store

`memory.jsonl` holds entries with a fixed schema
(`id, created_at, updated_at, fingerprint, kind, text, tags, importance, ttl_days,
file, line, source`). `MemoryStore` (mnemodex/store.py):

- **append** = read-prior + append + atomic replace under a lock file (never loses
  history, never corrupts concurrently).
- **gc** = TTL expiry, fingerprint dedupe (same token fingerprint ⇒ duplicate),
  hard-cap trimming. `mnemodex gc` triggers it manually; the store self-limits.
- **kinds** = decision, gotcha, tip, api, convention, task, note. Each has an icon
  and label in `KIND_META`; `--no-autocategorize` bypasses keyword sniffing.

Ranking (`Memory.recall`) = token-overlap × 4 + substring hits × 1.5 + recency
bonus + 0.5 × importance. A query needs at least one exact token overlap *or* a
substring hit — "cache" matches a memory about "cached tokens".

## Search index

`mnemodex/search.py` is the workhorse behind `search`, `symbol`, `ask` and the MCP
tools:

- Term frequencies per file from a character-class word splitter (no tokenizer
  needed). Scores are TF-IDF with normalization, a path bonus (short paths, tests)
  and a symbol-name bonus (files declaring a symbol matching the query rank up).
- n-gram fuzzy: trigrams of query and indexed words give tolerance to typos.
- `lookup_symbol(name)` is an exact-ish symbol-name index with `@line` disambiguation.
- Deterministic: `from_dict`/`to_dict` round-trips byte-identically.

## Knowledge graph

`mnemodex/graph.py` — nodes:

- `f:<path>` files (attrs: language, size, lines, code_tokens, mtime)
- `s:<path>:<name>@<line>` symbols (attrs: kind, signature, doc)

Edges: `import` (file→file), `define` (file→symbol), `ref` (file→symbol), `contains`
(folder→file). The graph is an adjacency map with typed edges; algorithms:

- `shortest_path` (BFS), `k_hop` neighbourhood, `connected_components`
- `page_rank` / `hub_score` — which files does everything depend on? Which
  files are the chokepoints of your build?

Export: Graphviz `to_dot()` for rendering, JSON for tooling.

## Context packs

`mnemodex/compress.py` assembles the `ask` output inside a token budget:

1. Matching memory entries (highest score first)
2. Matching symbols with signatures
3. Code snippets (bounded lines around definitions/refs)
4. Dependents of matched files (via graph edges, bounded)
5. Fallback: largest least-referenced files when the budget remains

`estimate_tokens` (mnemodex/util.py) is a ~1:4 word/char heuristic; everything is
fits-and-drops, so a tiny `--budget` still yields *useful* context, not truncation.

## MCP server

`mnemodex/mcp.py` implements JSON-RPC 2.0 over stdio (framed) or SSE. It reuses the
same `Session` (mnemodex/session.py) as the CLI: lazy store discovery, lazy index
load, shared memory facade. Tools and their wiring are declared in one registry, so
the CLI, MCP and web UI can never drift apart. See `docs/MCP.md`.

## Web UI

`mnemodex/webui/` = `ThreadingHTTPServer` + JSON API + a single vanilla-JS SPA
(`index.html`): search, memory timeline, add/forget forms, and a hand-written
force-directed SVG graph view. No build step, no node_modules — the ship-it-and-
delete-it philosophy again.

## Determinism & privacy

- Deterministic output: same repo ⇒ same index bytes (bounded by timestamps in
  `created_at`/`mtime` metadata fields).
- Repo-relative paths only: index.json stores `src/cache/lru.py`, never
  `/Users/you/proj/...`. Memory entries store `--ref` values verbatim, so write
  repo-relative refs.
- `index.json` never contains file *contents* — only terms, symbol signatures and
  snippets trimmed by lines, by design (index is small, cheap to rebuild).

## Why stdlib-only?

Dependencies are trust: every dep is code you didn't read running in your agent's
loop. The Python stdlib has everything needed — `json`, `os`, `re`, `argparse`,
`http.server`, `subprocess`. Cost of this choice: no SQLite backend, no async
HTTP, no embeddings. All three are carded as *optional* future tiers, never
runtime requirements.