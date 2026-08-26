# Contributing to mnemodex

First off — thank you for considering a contribution. mnemodex is built for
AI coding agents, and it is only as good as the community that shapes it.
This guide covers dev setup, coding conventions, and how to land changes
cleanly. The project is MIT licensed and 100% Python standard library —
zero dependencies, Python ≥ 3.9. That contract is a hard requirement, not a
preference.

## Development setup

1. Clone the repository:

   ```sh
   git clone https://github.com/beijixingdeyan/mnemodex
   cd mnemodex
   ```

2. (Optional) `pip install -e ".[dev]"` for the `mnemodex` console script and
   the `pytest`/`ruff` extras — but the canonical test runner needs nothing
   installed and is what CI runs:

   ```sh
   python -m unittest discover -s tests
   ```

   The suite is ~104 tests, no network, no external tools, well under a
   second. Everything green before you push.

## Coding conventions

- **Standard library only.** Never add a third-party dependency — runtime or
  build-time — without an RFC. Open an issue proposing it, explain what
  problem it solves and why the standard library cannot, and wait for
  consensus before writing code. This keeps mnemodex pip-installable and
  trustworthy in locked-down environments.
- **Type hints everywhere.** Modules start with `from __future__ import
  annotations` and annotate every signature with precise `typing` types.
- **Module docstrings.** Every module opens with a docstring explaining what
  it does and why; public functions get at least a one-line summary.
- **Style.** Follow the existing code: 4-space indent, 100-column lines
  (the shipped `[tool.ruff]` config matches).
- **Errors.** Raise `MnemodexError` subclasses (see `mnemodex/errors.py`)
  for user-facing failures — the CLI and MCP server render them politely.
- **Python floor is 3.9.** Nothing that breaks on 3.9 in new code.

## Adding a new language extractor

Indexing supports two tiers per language: **search indexing** (lexing,
comments, keywords — always available) and **symbol extraction** (functions,
classes, imports — richer graph and `symbol` output). Adding a language
touches three files plus tests:

1. **`mnemodex/languages.py`** — register the language in the `LANGUAGES`
   dict: file extensions (`exts`), comment styles (`comments`), keyword set
   (`keywords`). This alone is a complete addition if you skip symbol
   extraction.
2. **`mnemodex/lexer.py`** — only if the language needs a lexer feature the
   registry cannot express (a new comment style, bracket-quote strings).
   Lexer config is driven by the language spec, so usually nothing to do.
3. **`mnemodex/symbols.py`** — write an extractor returning an
   `ExtractionResult` (symbols + imports) and register it in the
   `_EXTRACTORS` dict. Languages without an extractor are still indexed for
   search and the graph, just without symbol nodes.
4. **`tests/test_symbols.py`** — parse a short fixture and assert the
   extracted symbols/imports. Every registry entry is covered by a test;
   new ones must be too.

## Adding a new CLI subcommand

1. **`mnemodex/cli.py`** — in `_build_parser()`, add the subparser:

   ```python
   p = sub.add_parser("name", help="one-line help")
   p.add_argument("--flag", ...)
   p.set_defaults(fn=cmd_name)
   ```

2. Implement `def cmd_name(args, log) -> int` returning an exit code
   (0 = success); dispatch happens via `args.fn`.
3. Update the **completion scripts**: add the command to
   `_COMPLETE_COMMANDS` and, if it takes arguments, to the per-shell
   scripts in `COMPLETIONS`.
4. Add a test in **`tests/test_cli.py`** that runs the command in a temp
   repo (see existing tests for the fixture pattern) and asserts output
   and exit code.
5. Update the usage block in the `cli.py` module docstring.

## How new MCP tools are registered

MCP tools live in **`mnemodex/mcp.py`**: a `Tool` — name, description, JSON
Schema `input_schema`, handler — appended to the `tools` list in
`build_tools()`:

```python
Tool(
    "mnemodex_my_tool",
    "What the tool does and when an agent should call it.",
    {"type": "object", "properties": {...}, "required": [...]},
    my_handler,
)
```

Rules:

- Tool names are prefixed `mnemodex_` (e.g. `mnemodex_recall`).
- The server speaks **JSON-RPC 2.0**: handlers must return **dict-shaped
  results** (wrapped as `{"jsonrpc": "2.0", "id": ..., "result": ...}`).
  Return `{"_error": "message"}` for a clean failure; raise
  `MnemodexError` for known error conditions.
- Add a test in **`tests/test_mcp.py`** covering happy and error paths over
  `tools/call`. `tools/list`, `initialize`, `ping`, and notifications are
  already handled — extend them only if the protocol demands it.

## Pull request guidelines

- **One logical change per PR** — a language extractor, a CLI subcommand, or
  a bugfix, not a mix.
- **Tests are required.** Bugfixes ship a regression test; features ship
  behavior tests.
- **Keep the diff small.** If a change needs a large diff, split it and land
  the pieces in sequence.
- **Link the issue** the PR resolves in the description.
- **Docs follow behavior.** User-visible changes update the README, the CLI
  usage block, and `CHANGELOG.md` under `[Unreleased]`.
- Run the full suite before pushing: `python -m unittest discover -s tests`.

## Commit message style

Use [Conventional Commits](https://www.conventionalcommits.org/):

```text
feat(index): add memory TTL tiers
fix(search): rank ngram matches above keyword hits
docs(gif): document the palette contract
test(gif): assert deterministic output
chore: bump INDEX_FORMAT_VERSION
```

Type prefixes: `feat`, `fix`, `docs`, `refactor`, `test`, `perf`, `chore`.
Scope is the touched area (`index`, `search`, `store`, `mcp`, `gif`, `cli`,
`web`). Keep the summary under 72 characters; explain *why* in the body.

## Getting help

- **Questions & ideas** — GitHub Discussions.
- **Bug reports** — GitHub Issues with reproduction steps, expected vs.
  actual behavior, and the output of `mnemodex version`.
- **Behavior-changing proposals** — open an RFC-style issue first and invite
  feedback before implementing.

Not sure whether a change fits? Ask in an issue before writing code — it
saves everyone time. Thanks for helping mnemodex grow.