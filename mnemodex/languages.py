"""Language registry for the mnemodex indexer.

Defines which file extensions map to which language, the comment syntaxes a
language uses (so the lexer can skip them), and the set of keywords the
lexer should tag. Adding a language is a one-file change:

    1. register its extensions here,
    2. add a ``SymbolExtractor`` in :mod:`mnemodex.symbols` (optional —
       languages without an extractor are still indexed for search and the
       graph, just without symbol nodes).

The set is intentionally opinionated and focused on what real codebases
contain; every entry is covered by a test.
"""

from __future__ import annotations

import os
from typing import Dict, Iterable, List, Optional, Tuple

# ---------------------------------------------------------------------------
# comment styles
# ---------------------------------------------------------------------------
LINE = "line"
BLOCK = "block"
LINE_BLOCK = "line_block"  # block comments exist but line comments dominate
HASH_LINE = "hash_line"
HTML_COMMENT = "html_comment"
DOCSTRING = "docstring"


def _kw(*words: str) -> Tuple[str, ...]:
    """Build a keyword tuple from one or more whitespace-separated strings."""
    out: List[str] = []
    for chunk in words:
        out.extend(chunk.split())
    return tuple(out)


LANGUAGES: Dict[str, dict] = {
    "python": {
        "exts": (".py", ".pyw", ".pyi"),
        "comments": (HASH_LINE, DOCSTRING),
        "keywords": _kw(
            "and as assert async await break class continue def del elif else except finally for from global if import in is lambda nonlocal not or pass raise return try while with yield match case True False None"
        ),
    },
    "javascript": {
        "exts": (".js", ".mjs", ".cjs", ".jsx"),
        "comments": (LINE_BLOCK,),
        "keywords": _kw(
            "async await break case catch class const continue debugger default delete do else export extends finally for function if import in instanceof let new of return static super switch this throw try typeof var void while with yield true false null undefined"
        ),
        "bracket_strings": ("`",),
    },
    "typescript": {
        "exts": (".ts", ".tsx", ".mts", ".cts"),
        "comments": (LINE_BLOCK,),
        "keywords": _kw(
            "abstract any as asserts async await bigint boolean break case catch class const constructor continue declare debugger default delete do else enum export extends false finally for from function get implements import in infer instanceof interface is keyof let module namespace never new null number object of package override private protected public readonly require return set static string super switch symbol this throw true try type typeof undefined unique unknown var void while with yield"
        ),
        "bracket_strings": ("`",),
    },
    "rust": {
        "exts": (".rs"),
        "comments": (LINE, BLOCK),
        "keywords": _kw(
            "as async await break const continue crate dyn else enum extern false fn for if impl in let loop match mod move mut pub ref return self Self static struct super trait true type unsafe use where while"
        ),
    },
    "c": {
        "exts": (".c", ".h"),
        "comments": (LINE_BLOCK,),
        "keywords": _kw(
            "auto break case char const continue default do double else enum extern float for goto if inline int long register restrict return short signed sizeof static struct switch typedef union unsigned void volatile while"
        ),
    },
    "cpp": {
        "exts": (".cc", ".cpp", ".cxx", ".hpp", ".hh", ".hxx", ".h++", ".ipp", ".inl"),
        "comments": (LINE_BLOCK,),
        "keywords": _kw(
            "alignas alignof and and_eq asm auto bitand bitor bool break case catch char char8_t char16_t char32_t class compl concept const consteval constexpr constinit const_cast continue co_await co_return co_yield decltype default delete do double dynamic_cast else enum explicit export extern false float for friend goto if inline int long mutable namespace new noexcept not not_eq nullptr operator or or_eq private protected public register reinterpret_cast requires return short signed sizeof static static_assert static_cast struct switch template this thread_local throw true try typedef typeid typename union unsigned using virtual void volatile wchar_t while xor xor_eq"
        ),
    },
    "java": {
        "exts": (".java"),
        "comments": (LINE_BLOCK,),
        "keywords": _kw(
            "abstract assert boolean break byte case catch char class const continue default do double else enum extends final finally float for goto if implements import instanceof int interface long native new package private protected public return short static strictfp super switch synchronized this throw throws transient try void volatile while true false null record sealed permits non-sealed var yield"
        ),
    },
    "go": {
        "exts": (".go"),
        "comments": (LINE, BLOCK),
        "keywords": _kw(
            "break case chan const continue default defer else fallthrough for func go goto if import interface map package range return select struct switch type var"
        ),
    },
    "ruby": {
        "exts": (".rb", ".rake", ".gemspec"),
        "comments": (HASH_LINE,),
        "keywords": _kw(
            "BEGIN END alias and begin break case class def defined do else elsif end ensure false for if in module next nil not or redo rescue retry return self super then true undef unless until when while yield"
        ),
    },
    "shell": {
        "exts": (".sh", ".bash", ".zsh"),
        "comments": (HASH_LINE,),
        "keywords": _kw(
            "if then else elif fi for while until do done case esac function in select time coproc return local readonly export unset set shift source alias unalias trap exit"
        ),
    },
    "json": {"exts": (".json", ".jsonl", ".geojson"), "comments": (), "keywords": ()},
    "yaml": {
        "exts": (".yml", ".yaml"),
        "comments": (HASH_LINE,),
        "keywords": (),
    },
    "toml": {
        "exts": (".toml"),
        "comments": (HASH_LINE,),
        "keywords": (),
    },
    "markdown": {
        "exts": (".md", ".markdown", ".mdx"),
        "comments": (),
        "keywords": (),
        "no_symbols": True,
    },
    "html": {
        "exts": (".html", ".htm", ".xhtml"),
        "comments": (HTML_COMMENT,),
        "keywords": (),
        "no_symbols": True,
    },
    "css": {
        "exts": (".css", ".scss", ".less"),
        "comments": (LINE_BLOCK,),
        "keywords": (),
        "bracket_strings": ("`",),
    },
    "sql": {
        "exts": (".sql"),
        "comments": (LINE, BLOCK),
        "keywords": _kw(
            "select from where insert into values update set delete create table index view alter drop join inner left right full outer on group by order having limit offset union all distinct as and or not null primary key foreign references default check unique"
        ),
    },
    "dockerfile": {
        "exts": (),
        "names": ("Dockerfile", "Containerfile"),
        "comments": (HASH_LINE,),
        "keywords": (),
        "no_symbols": True,
    },
    "makefile": {
        "exts": (),
        "names": ("Makefile", "makefile", "GNUmakefile", "CMakeLists.txt"),
        "comments": (HASH_LINE,),
        "keywords": (),
        "no_symbols": True,
    },
}

_EXT_INDEX: Dict[str, str] = {}
for _name, _spec in LANGUAGES.items():
    exts = _spec.get("exts", ())
    if isinstance(exts, str):
        exts = (exts,)
    for _ext in exts:
        _EXT_INDEX[_ext.lower()] = _name

_NAME_INDEX: Dict[str, str] = {}
for _name, _spec in LANGUAGES.items():
    names = _spec.get("names", ())
    if isinstance(names, str):
        names = (names,)
    for _basename in names:
        _NAME_INDEX[_basename] = _name


def language_for_path(path: str) -> Optional[str]:
    """Best-effort language name from the file name/extension."""
    base = os.path.basename(path)
    if base in _NAME_INDEX:
        return _NAME_INDEX[base]
    ext = os.path.splitext(base)[1].lower()
    return _EXT_INDEX.get(ext)


def all_language_names() -> Tuple[str, ...]:
    return tuple(sorted(LANGUAGES.keys()))


def spec_for(name: str) -> Optional[dict]:
    return LANGUAGES.get(name)


def extensions_of(name: str) -> Tuple[str, ...]:
    spec = LANGUAGES.get(name, {})
    return spec.get("exts", ())


def filter_languages(requested: Iterable[str]) -> Tuple[str, ...]:
    """Resolve a config `languages` list against the registry."""
    out: List[str] = []
    for raw in requested:
        name = raw.strip().lower()
        if name == "auto":
            return all_language_names()
        if name in LANGUAGES:
            out.append(name)
    return tuple(out)


def classify(path: str) -> dict:
    """Return the language spec dict (or {}) for a path."""
    name = language_for_path(path)
    return LANGUAGES.get(name, {})