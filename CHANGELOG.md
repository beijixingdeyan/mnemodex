# Changelog

All notable changes to mnemodex will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

The project has not shipped a tagged release yet; this changelog tracks
progress toward **0.1.0**, the initial release.

## [Unreleased]

### Added

- **Stdlib-only indexing (19 languages)** — a pure-Python lexer and symbol
  extractors with zero runtime dependencies, so the index builds anywhere
  Python 3.9+ runs.
- **Agent memory store** — durable, append-only memory for decisions,
  gotchas, tips, API notes, conventions, tasks, and free-form notes, with
  tags, importance ratings, TTLs, automatic categorization, and dedupe.
- **Knowledge graph** — codebase graph built from import, reference, and
  definition edges, with BFS traversal (shortest path, k-hop, connected
  components) and deterministic PageRank.
- **TF-IDF + ngram search** — ranked free-text file search with
  camelCase/snake_case normalization and stopword filtering.
- **MCP server (stdio + SSE)** — a JSON-RPC 2.0 server exposing 10 tools:
  `recall`, `add`, `context`, `lookup_symbol`, `files`, `read_file`,
  `forget`, `list_memory`, `stats`, and `git`.
- **Context Pack** — budgeted prompt assembly (`ask` / `mnemodex_context`)
  that packs memory, symbols, snippets, and dependents within a token budget.
- **Zero-config web UI** — a single-file, dependency-free browser UI started
  with `mnemodex web`.
- **Git-aware summaries** — recent commits, hot files, and branch context so
  agents can ground work in the current repository state.
- **Bundled agent skills** — ready-to-use skills for Cursor (rules) and
  Codex (agent files).
- **Installers & completions** — a `mnemodex` console script and shell
  completion scripts for bash, zsh, fish, and PowerShell.
- **Self-contained GIF renderer** — a from-scratch GIF89a encoder that
  regenerates `docs/demo.gif` with `mnemodex gif`, with no image library.
- **104-test suite** — unit tests covering the lexer, extractors, indexer,
  graph, search, store, MCP server, CLI, and GIF writer, all standard-library
  only and network-free.