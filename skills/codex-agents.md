# AGENTS.md (for Codex, Gemini CLI, Cline, Aider — or any coding agent)

This file is auto-generated guidance; it lives at the repo root after
`mnemodex export agent`. Keep it small and let mnemodex hold the details.

## Operating rules

1. **Check memory before editing.** If the repo has `.mnemodex/`, run:

   ```bash
   mnemodex ask "<topic you are about to work on>"
   ```

   Use the returned context pack (memory + symbols + impact) before writing
   code. This is faster and more accurate than inferring from scratch.

2. **Write memory after learning.** Persist facts with:

   ```bash
   mnemodex add "<fact>" --kind <kind> --tags <tags> [--ref <path>]
   ```

   Kinds: `decision` (choices + why), `gotcha` (symptoms + fixes),
   `convention` (style/naming), `api` (contracts), `tip`, `task`, `note`.

3. **Resolve before guessing**: `mnemodex symbol <name>` finds definitions;
   `mnemodex search "<query>"` finds files.

## Why

Coding agents forget between sessions. Mnemodex is a local-first, zero
-dependency memory layer that survives restarts — your learnings this session
are available next session, to teammates, and to CI.