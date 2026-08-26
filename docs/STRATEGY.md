# Strategy — why mnemodex exists, and why it will survive contact with your repo

This document is the "design rationale" part of the repo. It answers the five
questions anyone should ask before building a developer tool, shows the options we
considered and rejected, and compares honestly against the alternatives you may
already know.

## The five questions

1. **What problem, exactly?**
   AI coding agents are stateless per session. Every new session re-reads the repo,
   re-derives the conventions and re-learns the gotchas the team already paid for.
   The wasted tokens are the small cost; the large one is the *quality* — an agent
   that must re-derive "tokens expire after 60s" from a million lines will sometimes
   get it wrong. mnemodex makes the hard-won knowledge a first-class artifact of the
   repo: durable, queryable, ranked, and available to any agent in one command.

2. **Who is this for?**
   Solo developers and small teams who use AI agents (Claude Code, Cursor, Codex,
   Copilot, custom agents) on codebases they did not write yesterday, plus anyone
   who wants a zero-dependency, scriptable code-intelligence index without adopting
   a heavyweight language server or a SaaS. It is for people who distrust "just
   install this 400 MB runtime" installers.

3. **Why now?**
   Agent usage is exploding while the *memory layer* is still either proprietary,
   cloud-based, or bolted onto a single vendor's agent. The window is open for a
   **local, vendor-neutral, protocol-first** memory index that works with *whatever*
   agent the user runs next year. The MCP protocol standardized the pipe; nobody has
   standardized the memory *content* — that is exactly the seat we're taking with
   `.mnemodex/index.json` format v1.

4. **Why will people care in six months?**
   Because a repo with `.mnemodex/` gets *measurably better agent outcomes*:
   - less re-discovery (context packs are pre-ranked, budgeted);
   - fewer repeat mistakes (gotchas replay into every session);
   - reproducible index (CI-diffable, no embeddings drift).
   Once the memory file exists, leaving it is worse than keeping it — the same
   network effect every build artifact has.

5. **What would make this fail?**
   The right-sized competitor (a vendor ships a better local memory layer), or
   apathy in the index format w/o adoption. Mitigations: keep the format tiny and
   documented (it is: JSON + JSONL, version 1), make the CLI so pleasant that
   `init && index` is a habit, and stay vendor-neutral forever (memory is *yours*).

## Proposals considered

| proposal | verdict | why |
| --- | --- | --- |
| **A. Memory-only sticky notes** (a glorified `notes.jsonl` + MCP) | rejected | too thin: doesn't make the *code itself* answerable, no graph, no search — a one-afternoon clone |
| **B. Full semantic index** (embeddings + vector store + PostgreSQL) | rejected | that is the generic RAG play; heavy runtime, flaky reproducibility, and it fails the "zero dependencies / one command" promise this project sells |
| **C. LSP-driven index** (wrap tree-sitter / rust-analyzer) | rejected | tree-sitter is a native dep we'd have to ship for every platform; LSPs are heavy and language-specific — the opposite of "index 19 languages with the stdlib" |
| **D. I. mnemodex: local agent memory + knowledge graph + context packs, stdlib-only** | **chosen** | memory is the differentiator (need A), code intelligence is the moat (need B/C), and the no-dependency constraint forces a *simpler, more robust* design than any of the rejected options |

The strongest pushback we held ourselves to: *"an index without embeddings can't be
good."* The answer is in the design: deterministic TF-IDF + n-grams + symbol-name
boosts beat flaky embeddings for **exact-symbol and code-structure queries**, which
is most of what agents need, while `lookup_symbol`/graph edges cover the rest.
Embeddings remain an optional future tier.

## Differentiation

### vs. claude-mem & friends (memory-only tools)

claude-mem and similar are notebook-style memory: entries you type, recalled into
the prompt. mnemodex does that **and** *derives* knowledge from the code itself
(symbols, imports, references), so even a repo with zero recorded memories answers
`ask "cache eviction"` with snippets and neighbours, not silence. And mnemodex has
no dependency on a single vendor's agent — it speaks MCP *and* exports plain files
(`CLAUDE.md`, `AGENTS.md`, Cursor rules) for whichever agent shows up.

### vs. code-graph / Astra / sourcegraph-style indexes

Those are read-only code maps: you can navigate, but they know nothing about what
your team learned. mnemodex is a **code map + experience memory** in one artifact:
the graph answers "what touches X", memory answers "what did we learn about X".
Also, without a server component mnemodex runs everywhere a `python3` runs —
laptops, CI, sandboxes, dockerless boxes — and indexes in seconds, not minutes.

### vs. browser-use-style automation

Different errand entirely: that family automates browsers; mnemodex automates
*remembering*. The overlap is philosophical — both are "agent infrastructure" — so
we state clearly: mnemodex does not browse, does not click, does not phone home.
Agents that browse *benefit* from mnemodex by remembering what they learned while
browsing.

## The three product bets

1. **Memory is content, not plumbing.** The format (`.jsonl`, versioned, diffable)
   is the product; the CLI/MCP/web are interchangeable front doors to the same
   store. Bet: whoever owns the *content layer* wins the agent-memory market.
2. **Zero-dependency as a competitive moat, not an accident.** One-liner install,
   runs in any sandbox, no supply-chain audit burden. Bet: "install friction" will
   be a bigger adoption killer than "fewer features" for this audience.
3. **Plain files over databases.** JSON/JSONL + atomic renames = git-diffable,
   backup-able, trivially portable. Bet: developers trust files they can `cat`.

## Roadmap & risk

Headline roadmap lives in `ROADMAP.md`. Risk register:

- **Low** — parse crashes on weird code: the lexer never raises; worst case a file
  contributes no symbols. Fuzz with `python -m mnemodex index` on odd repos; file
  issues, no CVAs.
- **Medium** — index size on giant monorepos: bounded by max-depth/max-bytes
  defaults; 0.3 adds mmap tokenizer + incremental indexing.
- **Medium** — "another CLI" fatigue: mitigated by the one-liner install and the
  MCP/export paths that require *zero* CLI usage from the agent itself.
- **High (and embraced)** — a vendor bundles local memory into their agent: our
  answer is the open format + vendor neutrality; if your agent ships memory, that
  memory should be this file.