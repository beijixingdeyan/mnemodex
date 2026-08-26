"""A dependency-free multi-language lexer.

Turn source text into a stream of :class:`Token` objects. One tokenizer
handles every registered language: comments and string styles are selected
per language, while identifiers, numbers and punctuation use one shared
scanner. The lexer never raises on weird input — unexpected characters
become ``punct`` tokens, so a strange file cannot crash an index run.

Tokens
------
* ``ident``   — identifiers (``_`` and unicode letters allowed)
* ``keyword`` — identifiers that are keywords in that language
* ``number``  — integer / float / hex / binary / octal literals
* ``string``  — quoted strings ('' , "" , `` `` ``, incl. escapes)
* ``comment`` — line comments, block comments, hash comments, HTML comments
* ``docstring`` — Python triple-quoted docstrings
* ``punct``   — operators and punctuation (one char per token)
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from .errors import LexError

IDENT_START = r"[^\W\d]"
IDENT_PART = r"[\w]"
_ID_RE = re.compile(r"[^\W\d][\w]*")
_NUM_RE = re.compile(
    r"(?:0[xX][0-9a-fA-F_]+|0[bB][01_]+|0[oO][0-7_]+|"
    r"(?:\d[\d_]*)?\.\d[\d_]*(?:[eE][+-]?\d+)?|"
    r"\d[\d_]*(?:[eE][+-]?\d+)?)"
)


class Token:
    __slots__ = ("kind", "value", "line", "col", "offset", "length")

    def __init__(self, kind: str, value: str, line: int, col: int, offset: int, length: int):
        self.kind = kind
        self.value = value
        self.line = line
        self.col = col
        self.offset = offset
        self.length = length

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Token({self.kind!r}, {self.value!r} @ {self.line}:{self.col})"

    def to_dict(self) -> Dict[str, object]:
        return {
            "kind": self.kind,
            "value": self.value,
            "line": self.line,
            "col": self.col,
            "offset": self.offset,
            "length": self.length,
        }


class LexConfig:
    """Per-language lexer configuration."""

    __slots__ = (
        "line_comments",
        "block_comments",
        "nested_blocks",
        "hash_line",
        "docstrings",
        "bracket_strings",
        "keywords",
        "unicode_idents",
    )

    def __init__(
        self,
        line_comments: Tuple[str, ...] = (),
        block_comments: Tuple[Tuple[str, str], ...] = (),
        nested_blocks: bool = False,
        hash_line: bool = False,
        docstrings: bool = False,
        bracket_strings: Tuple[str, ...] = (),
        keywords: Tuple[str, ...] = (),
        unicode_idents: bool = True,
    ):
        self.line_comments = line_comments
        self.block_comments = block_comments
        self.nested_blocks = nested_blocks
        self.hash_line = hash_line
        self.docstrings = docstrings
        self.bracket_strings = bracket_strings
        self.keywords = set(keywords)
        self.unicode_idents = unicode_idents

    @classmethod
    def for_language(cls, language: Optional[str]) -> "LexConfig":
        """Build a LexConfig from a languages.py spec (or defaults)."""
        from . import languages

        spec = languages.spec_for(language or "") or {}
        comments = spec.get("comments", ())
        line_comments: List[str] = []
        block_comments: List[Tuple[str, str]] = []
        hash_line = False
        docstrings = False
        for style in comments:
            if style == languages.LINE:
                line_comments.append("//")
            elif style == languages.LINE_BLOCK:
                line_comments.append("//")
                block_comments.append(("/*", "*/"))
            elif style == languages.BLOCK:
                block_comments.append(("/*", "*/"))
            elif style == languages.HASH_LINE:
                hash_line = True
            elif style == languages.DOCSTRING:
                docstrings = True
            elif style == languages.HTML_COMMENT:
                block_comments.append(("<!--", "-->"))
        return cls(
            line_comments=tuple(line_comments),
            block_comments=tuple(block_comments),
            nested_blocks=(language == "rust"),
            hash_line=hash_line,
            docstrings=docstrings,
            bracket_strings=tuple(spec.get("bracket_strings", ())),
            keywords=tuple(spec.get("keywords", ())),
        )


class Lexer:
    """Tokenize *text* using *config*."""

    def __init__(self, text: str, config: LexConfig):
        self.text = text
        self.config = config
        self.tokens: List[Token] = []

    def tokenize(self) -> List[Token]:
        text = self.text
        n = len(text)
        i = 0
        line = 1
        col = 0

        def advance(k: int) -> str:
            """Advance *k* chars from position i, tracking lines."""
            nonlocal i, line, col
            chunk = text[i : i + k]
            newlines = chunk.count("\n")
            if newlines:
                line += newlines
                col = len(chunk) - chunk.rfind("\n") - 1
            else:
                col += k
            i += k
            return chunk

        cfgs = self.config
        while i < n:
            ch = text[i]

            # whitespace
            if ch in " \t\r\n\f\v":
                advance(1)
                continue

            # line comments
            matched_line_comment = False
            for prefix in cfgs.line_comments:
                if text.startswith(prefix, i):
                    start = i
                    j = text.find("\n", i)
                    end = n if j == -1 else j
                    advance(end - start)
                    self.tokens.append(self._tok_at(text, start, end, "comment"))
                    matched_line_comment = True
                    break
            if matched_line_comment:
                continue

            # hash line comments
            if cfgs.hash_line and ch == "#":
                start = i
                j = text.find("\n", i)
                end = n if j == -1 else j
                advance(end - start)
                self.tokens.append(self._tok_at(text, start, end, "comment"))
                continue

            # block comments (incl. docstrings & html comments)
            matched_block = False
            for openm, closem in cfgs.block_comments:
                if text.startswith(openm, i):
                    start = i
                    depth = 1
                    j = i + len(openm)
                    if cfgs.nested_blocks:
                        while j < n and depth:
                            if text.startswith(openm, j):
                                depth += 1
                                j += len(openm)
                            elif text.startswith(closem, j):
                                depth -= 1
                                j += len(closem)
                            else:
                                j += 1
                        end = j
                    else:
                        j = text.find(closem, i + len(openm))
                        end = n if j == -1 else j + len(closem)
                    advance(end - start)
                    self.tokens.append(self._tok_at(text, start, end, "comment"))
                    matched_block = True
                    break
            if matched_block:
                continue

            # python docstrings / triple-quoted strings
            if cfgs.docstrings and (text.startswith('"""', i) or text.startswith("'''", i)):
                delim = text[i : i + 3]
                start = i
                j = text.find(delim, i + 3)
                end = n if j == -1 else j + 3
                advance(end - start)
                self.tokens.append(
                    Token("docstring", text[start:end], self._line_of(text, start), 0, start, end - start)
                )
                continue

            # strings
            quote_chars = ['"', "'"] + list(cfgs.bracket_strings)
            for q in quote_chars:
                if ch == q:
                    start = i
                    j = i + 1
                    while j < n:
                        if text[j] == "\\":
                            j += 2
                            continue
                        if text[j] == q:
                            j += 1
                            break
                        j += 1
                    # multi-line strings: allow \n inside ("..." across lines ok in most langs)
                    end = j
                    advance(end - start)
                    self.tokens.append(self._tok_at(text, start, end, "string"))
                    matched_block = True
                    break
            if matched_block:
                continue

            # numbers
            if ch.isdigit() or (ch == "." and i + 1 < n and text[i + 1].isdigit()):
                m = _NUM_RE.match(text, i)
                if m:
                    end = m.end()
                    advance(end - i)
                    self.tokens.append(self._tok_at(text, m.start(), end, "number"))
                    continue

            # identifiers / keywords
            if cfgs.unicode_idents and (_ID_RE.match(ch) or ch == "_"):
                m = _ID_RE.match(text, i)
                if m is None:
                    m = re.compile(r"_[^\W\d]*").match(text, i)
                end = m.end()
                value = text[i:end]
                kind = "keyword" if value in cfgs.keywords else "ident"
                advance(end - i)
                self.tokens.append(self._tok_at(text, m.start(), end, kind))
                continue
            if not cfgs.unicode_idents and (ch.isascii() and (ch.isalpha() or ch == "_")):
                end = i
                while end < n and (text[end].isascii() and (text[end].isalnum() or text[end] == "_")):
                    end += 1
                value = text[i:end]
                kind = "keyword" if value in cfgs.keywords else "ident"
                advance(end - i)
                self.tokens.append(self._tok_at(text, i, end, kind))
                continue

            # fallback: punctuation
            advance(1)
            self.tokens.append(Token("punct", ch, line, col - 1, i - 1, 1))

        return self.tokens

    # -- helpers ------------------------------------------------------------

    def _line_of(self, text: str, offset: int) -> int:
        return text.count("\n", 0, offset) + 1

    def _make_token(self, text: str, start: int, end: int, kind: str, value: str) -> Token:
        line = self._line_of(text, start)
        col = start - (text.rfind("\n", 0, start) + 1)
        return Token(kind, value, line, col, start, end - start)

    def _tok_at(self, text: str, start: int, end: int, kind: str) -> Token:
        return self._make_token(text, start, end, kind, text[start:end])


def tokenize(text: str, language: Optional[str], config: Optional[LexConfig] = None) -> List[Token]:
    """Convenience one-shot tokenizer."""
    if config is None:
        config = LexConfig.for_language(language)
    return Lexer(text, config).tokenize()


def significant_tokens(tokens: List[Token]) -> List[Token]:
    """Drop comments/docstrings (strings/numbers are kept for search)."""
    return [t for t in tokens if t.kind not in ("comment", "docstring")]


def token_stats(tokens: List[Token]) -> Dict[str, int]:
    """Aggregate counters useful for index stats."""
    counts: Dict[str, int] = {}
    for t in tokens:
        counts[t.kind] = counts.get(t.kind, 0) + 1
    code = sum(counts.get(k, 0) for k in ("ident", "keyword", "number", "string", "punct"))
    return {"total": len(tokens), "code": code, **counts}