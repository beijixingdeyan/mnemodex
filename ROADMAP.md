# mnemodex Roadmap

## Vision

mnemodex gives AI coding agents a memory that survives across sessions and
projects. The one-line north star: **your agent should start every session
already knowing what this repository is, what it decided, and what it
learned.** Everything below serves that — staying local, staying
zero-dependency, and staying fast even as repositories grow.

Items are checkboxes so the roadmap doubles as a living backlog. Priorities
are set by community discussion — RFC-style issues and GitHub Discussions
decide what lands next.

## Now — 0.2.x

Themes: make memory smarter, make it stick across projects, and stop
requiring the human to type it in.

- [ ] **Memory TTL tiers** — per-kind and per-entry expiry policies (e.g.
      tips expire faster than decisions), with `gc` honoring them.
- [ ] **Cross-repo sticky memory** — a user-level memory that follows the
      agent across repositories, so conventions learned in one project
      inform the next.
- [ ] **Auto-gotcha extraction from git diffs** — mine commit history for
      warnings ("don't touch X", "Y breaks when...") so gotchas accumulate
      without being written by hand.

## Later — 0.3.x

Themes: scale to big code, and speak the language agents already speak.

- [ ] **Tolerance for large monorepos** — an mmap-backed tokenizer and
      incremental indexing, so re-indexing a million-line tree is a delta,
      not a rebuild.
- [ ] **Language Server Protocol surface** — expose the knowledge graph over
      LSP (definitions, references, workspace symbols) so editors and agents
      get the same intelligence the CLI has.

## Someday

Ideas that need a champion and a concrete design before they move up.

- [ ] **Native binary via Rust** — a compiled `mnemodex` core for sub-second
      cold starts and single-file distribution.
- [ ] **Plugin memory backends** — opt-in SQLite/Redis storage behind the
      existing store interface, for multi-process and server deployments.
- [ ] **Team memory sync** — share memory between team members with merge
      and conflict handling, keeping the local-first promise intact.

---

Have an idea that is not here? Open an issue — the roadmap belongs to the
community that uses mnemodex.