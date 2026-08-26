"""A from-scratch .gitignore matcher (no external dependencies).

Implements the gitignore grammar closely enough for repository indexing:

  * blank lines and ``#`` comments
  * ``!`` negation (later rules win)
  * trailing ``/`` ⇒ directory-only
  * leading ``/`` ⇒ anchored to the rule's base directory
  * patterns without a slash (other than a trailing one) match at any depth
  * ``*``  (any run of non-``/`` chars), ``?``, char classes ``[abc]``
  * ``**``  (globstar): ``**/foo``, ``foo/**``, ``a/**/b``
  * escaping with backslash

Sources are stored with *repo-relative* base directories so the matcher is
pure path-string logic (no absolute paths are ever compared, which keeps the
privacy contract and works identically on every OS).
"""

from __future__ import annotations

import os
import re
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

_POSIX_SEP = "/"


def _normalise(path: str) -> str:
    return path.replace("\\", "/").lstrip("/")


def _unescape(s: str) -> str:
    """Remove backslash escapes from a pattern (before translation)."""
    out: List[str] = []
    i = 0
    while i < len(s):
        if s[i] == "\\" and i + 1 < len(s):
            out.append(s[i + 1])
            i += 2
        else:
            out.append(s[i])
            i += 1
    return "".join(out)


def _translate_glob(pattern: str) -> str:
    """Translate a gitignore glob (without `!`) to a regex for a whole path."""
    out: List[str] = []
    i = 0
    n = len(pattern)
    while i < n:
        ch = pattern[i]
        if ch == "*":
            if i + 1 < n and pattern[i + 1] == "*":
                if i + 2 < n and pattern[i + 2] == "/":
                    out.append(r"(?:.*/)?")
                    i += 3
                elif i + 2 == n:
                    out.append(r".*")
                    i += 2
                else:
                    out.append(r".*")
                    i += 2
            else:
                out.append(r"[^/]*")
                i += 1
        elif ch == "?":
            out.append(r"[^/]")
            i += 1
        elif ch == "[":
            j = i + 1
            if j < n and pattern[j] in ("!", "^"):
                j += 1
            if j < n and pattern[j] == "]":
                j += 1
            while j < n and pattern[j] != "]":
                j += 1
            if j < n:
                body = pattern[i + 1 : j]
                if body.startswith("!"):
                    body = "^" + body[1:]
                out.append("[" + body + "]")
                i = j + 1
            else:
                out.append(re.escape(ch))
                i += 1
        else:
            out.append(re.escape(ch))
            i += 1
    return "".join(out)


class Rule:
    """One parsed gitignore line tied to a base directory (repo-relative)."""

    __slots__ = ("base", "negate", "dir_only", "anchored", "basename_only", "regex", "regex_dir", "source")

    def __init__(self, line: str, base: str, source: str):
        self.base = base
        self.source = source
        self.negate = line.startswith("!")
        if self.negate:
            line = line[1:]
        dir_only = line.endswith("/")
        if dir_only:
            line = line.rstrip("/")
        anchored = line.startswith("/")
        if anchored:
            line = line.lstrip("/")
        self.dir_only = dir_only
        self.anchored = anchored
        self.basename_only = "/" not in line
        regex = _translate_glob(_unescape(line))
        self.regex = re.compile(regex + r"\Z")
        self.regex_dir = re.compile(regex + r"/\Z")

    def matches(self, rel_to_base: str, is_dir: bool) -> Optional[bool]:
        """True/False when this rule matches, None otherwise."""
        m = None
        if self.anchored:
            m = self.regex.match(rel_to_base)
            if not m and is_dir and self.dir_only:
                m = self.regex_dir.match(rel_to_base + "/")
        elif self.basename_only:
            name = rel_to_base.rsplit("/", 1)[-1]
            m = self.regex.match(name)
        else:
            m = self.regex.match(rel_to_base)
            if not m and is_dir and self.dir_only:
                m = self.regex_dir.match(rel_to_base + "/")
        if not m:
            return None
        return not self.negate


def parse_rules(lines: Iterable[str], base: str, source: str) -> List[Rule]:
    rules: List[Rule] = []
    for raw in lines:
        line = raw.rstrip("\r\n").rstrip(" ")
        if not line or line.startswith("#"):
            continue
        if line.startswith("\\#") or line.startswith("\\!"):
            # escaped comment/negation marker — strip the escape
            line = line[1:]
        try:
            rules.append(Rule(line, base, source))
        except re.error:
            continue
    return rules


EMPTY_GITIGNORE = os.path.join(".git", "info", "exclude")


class RepoIgnore:
    """Stacked gitignore sources evaluated root → deepest (later rule wins).

    Sources are added with their *repo-relative* base directory; each path is
    tested against every source whose base is an ancestor (or equal) so
    nested .gitignore files override parent ones, exactly like Git.
    """

    def __init__(self) -> None:
        self.sources: List[List[Rule]] = []

    def add(self, base_rel: str, lines: Iterable[str], source: Optional[str] = None) -> None:
        base = _normalise(base_rel or ".")
        rules = parse_rules(lines, base, source or base)
        if rules:
            self.sources.append(rules)

    def _decide(self, rel_path: str, is_dir: bool) -> Optional[bool]:
        """Last matching rule's verdict for *rel_path* (None = no rule hit)."""
        rel = _normalise(rel_path)
        decision: Optional[bool] = None
        for rules in self.sources:
            hit_this_source: Optional[bool] = None
            for rule in rules:
                base = rule.base
                if base == ".":
                    rel_to_base = rel
                elif rel == base or rel.startswith(base + "/"):
                    rel_to_base = rel[len(base) + 1 :] if rel != base else ""
                else:
                    # basename-only rules from ancestor sources still apply:
                    # handled below by testing against the full rel path.
                    if rule.basename_only and not rule.anchored:
                        m = rule.regex.match(rel.rsplit("/", 1)[-1])
                        if m:
                            hit_this_source = not rule.negate
                    continue
                m = rule.matches(rel_to_base, is_dir)
                if m is not None:
                    hit_this_source = m
            if hit_this_source is not None:
                decision = hit_this_source
        return decision

    def ignored(self, rel_path: str, is_dir: bool = False) -> bool:
        """True when the last matching rule ignores this path.

        Like Git, an ignored parent directory prunes its whole subtree:
        ``build/`` ignores ``build/intermediate.o`` too.
        """
        rel = _normalise(rel_path)
        if rel == "" or rel == ".":
            return False
        parts = rel.split("/")
        for i in range(len(parts) - 1):
            ancestor = "/".join(parts[: i + 1])
            if self._decide(ancestor, True) is True:
                return True
        return self._decide(rel, is_dir) is True


def load_gitignore(repo_root: str, rel_dir: str = ".") -> List[Tuple[str, List[str]]]:
    """Read every .gitignore along the path *rel_dir* (root included).

    Returns [(base_rel, lines), ...] ordered root → deepest.
    """
    out: List[Tuple[str, List[str]]] = []
    parts = [p for p in _normalise(rel_dir).split("/") if p and p != "."]
    for depth in range(len(parts) + 1):
        base = _POSIX_SEP.join(parts[:depth]) or "."
        gi_path = os.path.join(repo_root, base, ".gitignore")
        if os.path.isfile(gi_path):
            try:
                with open(gi_path, "r", encoding="utf-8", errors="replace") as fh:
                    out.append((base, fh.readlines()))
            except OSError:
                pass
    return out


class IncrementalIgnore:
    """Cache built lazily while the indexer walks the tree.

    ``ignore_for(rel_dir)`` returns a RepoIgnore with every .gitignore along
    the path from the repo root (included) down to that directory.
    """

    def __init__(self, repo_root: str, extra_patterns: Optional[Sequence[str]] = None):
        self.repo_root = repo_root
        self._cache: Dict[str, RepoIgnore] = {}
        self._extra = list(extra_patterns or [])

    def ignore_for(self, rel_dir: str = ".") -> RepoIgnore:
        key = _normalise(rel_dir) or "."
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        gi = RepoIgnore()
        for base, lines in load_gitignore(self.repo_root, key):
            gi.add(base, lines)
        if self._extra:
            gi.add(".", [p if p.startswith("!") else "/" + p for p in self._extra], "config.ignore_patterns")
        self._cache[key] = gi
        return gi

    def ignored(self, rel_path: str, is_dir: bool = False) -> bool:
        parent = rel_path.rsplit("/", 1)[0] if "/" in rel_path else "."
        return self.ignore_for(parent).ignored(rel_path, is_dir)