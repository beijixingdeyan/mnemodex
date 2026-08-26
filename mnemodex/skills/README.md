# mnemodex — The Memory Index for AI Coding Agents

> Give your coding agent a durable memory of the repository: decisions, gotchas, conventions and a
> queryable code knowledge graph. Zero dependencies. One command. No cloud.

---

## (skill embedded — see SKILL.md.dist for the packaged asset)

This directory contains the *portable* Agent Skills definitions that ship
with mnemodex:

| file | destination | purpose |
| --- | --- | --- |
| `SKILL.md.dist` | `~/.claude/skills/mnemodex/SKILL.md` | Claude Code skill |
| `cursor-rules.dist` | `.cursor/rules/mnemodex.mdc` | Cursor rules (generated per repo by `mnemodex export agent`) |
| `codex-agents.dist` | `AGENTS.md` | Codex / generic agent brief |
| `hooks/pre-commit.dist` | `.git/hooks/pre-commit` or `lefthook` | auto-`gc` + freshness check |
| `firewall.dist` | any agent | "consult memory before editing" reminder |

Install anywhere (one command):

```bash
mkdir -p ~/.claude/skills/mnemodex && cp skills/SKILL.md.dist ~/.claude/skills/mnemodex/SKILL.md
```

The `mnemodex export agent` command does this automatically per repository
and also writes `CLAUDE.md` / `AGENTS.md` / Cursor rules.