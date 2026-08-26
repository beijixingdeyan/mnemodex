# Security Policy

Thanks for helping keep mnemodex safe. This project is local-first: it runs
on your machine, never phones home, and stores everything as plain files in
your repository. That is a feature — and it also means you should understand
what mnemodex trusts and what it does not.

## Scope

What this policy covers:

- **Parsing untrusted repository code.** `mnemodex index` lexes and extracts
  symbols from any code you point it at, including third-party code, vendored
  dependencies, and code that was never written to be safe to parse. The
  lexer, extractors, and GIF/LZW codecs must never read outside their inputs,
  execute code, or corrupt the store.
- **Memory files store agent information.** The memory store
  (`.mnemodex/memory.jsonl` and friends) records decisions, gotchas, tips,
  and API notes — including, potentially, sensitive details an agent learned
  about a codebase. Contents are plaintext by design. Do not commit a memory
  store to a public repository unless you are certain its contents are safe
  to share.
- **MCP surface.** The JSON-RPC 2.0 server (stdio/SSE) must validate input,
  refuse out-of-repo path traversal, and fail gracefully on malformed
  requests.

Out of scope:

- The security of the machine mnemodex runs on (its permissions are yours).
- Memory store confidentiality — the store is an unencrypted local file by
  design.
- Parse errors and crashes on malformed or hostile input. These are bugs,
  welcome as regular issues, but they are **not** security vulnerabilities
  and will not receive CVEs.

## Supported versions

| Version | Supported                     |
| ------- | ----------------------------- |
| 0.1.x   | ✅ Current, receives fixes    |
| < 0.1   | ❌ Not released / unsupported |

Only the latest `0.1.x` release line receives security fixes. If you are
pinned to an older patch, upgrade before reporting.

## Reporting a vulnerability

Please report security issues **privately**, before opening a public issue:

1. Preferred: open a **GitHub Security Advisory** ("Report a vulnerability"
   on the repository page) — this keeps the discussion private until a fix
   is released.
2. Alternative: email `security@mnemodex.dev` with a description of the
   issue. You are welcome to report anonymously.

Please include:

- The mnemodex version and platform (output of `mnemodex version`).
- A minimal reproduction — ideally a small file or transcript.
- What you expected, what happened, and why you consider it a security
  issue rather than a robustness bug.

### What to expect

- **Acknowledgment** within 48 hours.
- **A triage update** within 7 days: confirmed and scheduled, or an
  explanation of why it is out of scope.
- Fixes land in a patch release; we keep details private until users have a
  chance to upgrade.

## Contribute fixes

If you can, include a patch or a minimal reproducer with your report. Pull
requests that fix confirmed issues are welcome — see `CONTRIBUTING.md`.
Fuzzing the lexer, extractors, and GIF writer against the standard library's
`unittest` suite is a great way to find robustness bugs; if you find one,
file it as a regular issue (no need for the private channel).