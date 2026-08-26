"""Bundled Agent Skills (drop-in for Claude Code / Cursor / Codex / any agent).

These mirror the repo-level `skills/` directory at the community location
`~/.claude/skills/mnemodex/` etc. so agents get the skill with no setup.
"""

from __future__ import annotations

import os

SKILL_DIR = os.path.dirname(__file__)


def skill_path(name: str) -> str:
    return os.path.join(SKILL_DIR, name)