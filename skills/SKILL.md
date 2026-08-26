---
name: mnemodex
description: >
  Query and maintain the repository's durable memory (decisions, gotchas,
  conventions, API notes) and code knowledge graph. Use BEFORE editing code
  you haven't touched this session, and to persist anything non-obvious you
  learn. Zero-dependency local CLI: `mnemodex`.
---

# mnemodex — the memory index

Mnemodex keeps a local-first memory store (`.mnemodex/`) next to the repo.
It works with any agent that can run shell commands; no MCP client needed.

## When to invoke

- **Before editing** code you haven't touched this session:
  run `mnemodex ask "<topic>"` (token-budgeted context pack) or
  `mnemodex recall "<topic>"`.
- **After learning** something non-obvious (why a design is the way it is,
  a gotcha, a naming convention, an API contract):
  run `mnemodex add "<fact>" --kind <kind> --tags <tags>`.
- **Resolving symbols**: `mnemodex symbol "<name>"`.
- **Finding files**: `mnemodex search "<query>"`.

## Memory kinds

`decision` · `gotcha` · `tip` · `api` · `convention` · `task` · `note`

Rules of thumb:
- Save **decisions** with the *reason* and the *alternative rejected*.
- Save **gotchas** with the *symptom* and the *fix*.
- Save **conventions** so future edits match existing style.
- Always cite a repo-relative path when the fact is file-specific:
  `mnemodex add "…" --ref src/api/auth.py --line 41`.

## Example session

```bash
$ mnemodex ask "cache eviction"          # context: memory + symbols + impact
$ mnemodex add "auth tokens cached 5 min" --kind decision --tags cache
$ mnemodex add "cookie hashes change per release; cache key pins schema" \
    --kind gotcha --tags cache
$ mnemodex symbol invalidate_cache       # where is it defined?
```

## Notes

- The store is local and git-ignored by default; share teams' memory with
  `mnemodex export memory --format md`.
- All commands are offline. No API keys. No cloud.
- `mnemodex help` / `mnemodex <command> --help` for details.