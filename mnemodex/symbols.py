"""Language-aware symbol extraction on top of the lexer.

Given source text and a language name, produce:

* ``symbols``   — declared symbols (functions, classes, structs, enums,
  traits, interfaces, types, consts, methods, modules),
* ``imports``   — declared imports / dependencies on other code (*target*,
  *source moiety* like ``from x import y``),
* ``module_doc`` — the file-level docstring (Python) or leading comment.

The extractors are deliberately heuristic — they never *parse* the language.
They read the token stream and look for declaration shapes. This is robust
enough to be useful for search/graph purposes over real-world code and is
fully tested on the fixtures in ``tests/fixtures/``.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from .lexer import Token, significant_tokens, tokenize

KIND_FUNCTION = "function"
KIND_CLASS = "class"
KIND_METHOD = "method"
KIND_STRUCT = "struct"
KIND_ENUM = "enum"
KIND_TRAIT = "trait"
KIND_INTERFACE = "interface"
KIND_TYPE = "type"
KIND_CONST = "const"
KIND_MODULE = "module"
KIND_IMPL = "impl"
KIND_IMPORT = "import"
KIND_FIELD = "field"
KIND_HEADING = "heading"  # markdown headings, surfaced as symbols for docs

_ALL_KINDS = (
    KIND_FUNCTION, KIND_CLASS, KIND_METHOD, KIND_STRUCT, KIND_ENUM, KIND_TRAIT,
    KIND_INTERFACE, KIND_TYPE, KIND_CONST, KIND_MODULE, KIND_IMPL, KIND_IMPORT,
    KIND_FIELD, KIND_HEADING,
)

# primitive / modifier keywords that precede a function name in C-like langs
_C_LIKE_RETURNS = {
    "void", "int", "char", "float", "double", "long", "short", "unsigned",
    "signed", "bool", "size_t", "uint8_t", "uint16_t", "uint32_t", "uint64_t",
    "int8_t", "int16_t", "int32_t", "int64_t",
}
_C_LIKE_MODIFIERS = {
    "static", "inline", "const", "constexpr", "extern", "virtual", "explicit",
    "friend", "register", "volatile", "constinit", "consteval",
}
_JAVA_MODIFIERS = {
    "public", "private", "protected", "static", "final", "abstract",
    "synchronized", "native", "default", "strictfp", "transient", "volatile",
}
_RUST_MODS = {"pub", "pub(crate)", "pub(super)", "pub(self)"}


class Symbol:
    __slots__ = ("name", "kind", "line", "col", "signature", "doc", "parent")

    def __init__(
        self,
        name: str,
        kind: str,
        line: int,
        col: int,
        signature: str = "",
        doc: str = "",
        parent: str = "",
    ):
        self.name = name
        self.kind = kind
        self.line = line
        self.col = col
        self.signature = signature
        self.doc = doc
        self.parent = parent

    def to_dict(self) -> Dict[str, object]:
        return {
            "name": self.name,
            "kind": self.kind,
            "line": self.line,
            "col": self.col,
            "signature": self.signature,
            "doc": self.doc[:200],
            "parent": self.parent,
        }

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Symbol {self.kind} {self.name!r} @L{self.line}>"


class Import:
    __slots__ = ("target", "source", "line")

    def __init__(self, target: str, source: str = "", line: int = 0):
        self.target = target
        self.source = source
        self.line = line

    def to_dict(self) -> Dict[str, object]:
        return {"target": self.target, "source": self.source, "line": self.line}


class ExtractionResult:
    __slots__ = ("symbols", "imports", "module_doc")

    def __init__(self):
        self.symbols: List[Symbol] = []
        self.imports: List[Import] = []
        self.module_doc: str = ""


class _Cursor:
    """A lightweight cursor over significant tokens."""

    def __init__(self, tokens: List[Token]):
        self.tokens = tokens
        self.n = len(tokens)
        self.i = 0

    def at_end(self) -> bool:
        return self.i >= self.n

    def peek(self, k: int = 0) -> Optional[Token]:
        j = self.i + k
        return self.tokens[j] if j < self.n else None

    def next(self) -> Optional[Token]:
        if self.at_end():
            return None
        t = self.tokens[self.i]
        self.i += 1
        return t

    def skip(self, kinds=("punct", "number", "string")):
        while not self.at_end() and self.peek().kind in kinds:
            self.i += 1

    def skip_punct(self, *values):
        while True:
            t = self.peek()
            if t is None or t.kind != "punct" or (values and t.value not in values):
                return
            self.i += 1

    def match_punct(self, value: str) -> Optional[Token]:
        t = self.peek()
        if t is not None and t.kind == "punct" and t.value == value:
            self.i += 1
            return t
        return None

    def eat_balanced_parens(self) -> int:
        """Consume a balanced (...) group; returns tokens eaten."""
        start = self.i
        t = self.peek()
        if t is None or t.kind != "punct" or t.value != "(":
            return 0
        depth = 0
        while not self.at_end():
            tok = self.next()
            if tok.kind == "punct" and tok.value == "(":
                depth += 1
            elif tok.kind == "punct" and tok.value == ")":
                depth -= 1
                if depth == 0:
                    break
        return self.i - start

    def eat_to_line_end(self) -> int:
        """Consume tokens until the token line changes or EOF."""
        start = self.i
        line = self.peek().line if self.peek() else 0
        while not self.at_end() and self.peek().line == line:
            self.i += 1
        return self.i - start

    def signature_after_paren(self) -> str:
        """Callers have *already consumed* the opening `(`; scan to the
        matching `)` (depth starts at 1 so the first `)` terminates)."""
        depth = 1
        parts: List[str] = []
        while not self.at_end():
            t = self.next()
            parts.append(t.value)
            if t.kind == "punct" and t.value == "(":
                depth += 1
            elif t.kind == "punct" and t.value == ")":
                depth -= 1
                if depth == 0:
                    break
        return "".join(parts)


class _ClassDepth:
    """Tracks brace depth relative to enclosing class/impl blocks.

    `{` increments, `}` decrements; entries >= 1 mean we are inside a
    class/struct/impl body for the purpose of method detection.
    """

    def __init__(self):
        self.depth = 0

    def on_punct(self, value: str) -> None:
        if value == "{":
            self.depth += 1
        elif value == "}" and self.depth > 0:
            self.depth -= 1

    @property
    def inside(self) -> bool:
        return self.depth > 0


def _attach_doc(sym: Symbol, tokens: List[Token], index: int) -> None:
    """Look backwards for the nearest docstring/comment to attach as doc."""
    doc_parts: List[str] = []
    for j in range(index - 1, max(-1, index - 8), -1):
        t = tokens[j]
        if t.kind in ("comment", "docstring"):
            doc_parts.append(t.value.lstrip("#/ \t").strip())
            if t.line < tokens[index].line - 1:
                break
        elif t.kind in ("punct", "keyword") and t.value not in ("}", ";"):
            break
    sym.doc = "\n".join(reversed(doc_parts))[:400]


# ---------------------------------------------------------------------------
# per-language extractors
# ---------------------------------------------------------------------------

def extract_python(text: str) -> ExtractionResult:
    result = ExtractionResult()
    tokens = significant_tokens(tokenize(text, "python"))
    cur = _Cursor(tokens)
    raw = tokenize(text, "python")

    # module docstring
    for t in raw[:2]:
        if t.kind == "docstring":
            result.module_doc = t.value.strip('"\'')
            break
        if t.kind not in ("comment",):
            break

    class_stack: List[Tuple[str, int]] = []  # (name, col) — col pops at dedent
    while not cur.at_end():
        _probe = cur.i
        t = cur.peek()
        if t is None:
            break
        if t.kind == "keyword":
            if t.value == "def":
                idx = cur.i
                cur.next()
                cur.skip_punct()
                name_t = cur.peek()
                if name_t and name_t.kind == "ident":
                    # dedent: a def column <= top class column leaves that scope
                    while class_stack and name_t.col <= class_stack[-1][1]:
                        class_stack.pop()
                    cur.next()
                    sig = ""
                    if cur.match_punct("("):
                        sig = cur.signature_after_paren()
                    parent = class_stack[-1][0] if class_stack else ""
                    kind = KIND_METHOD if parent else KIND_FUNCTION
                    sym = Symbol(name_t.value, kind, name_t.line, name_t.col, f"def {name_t.value}{sig}", parent=parent)
                    _attach_doc(sym, raw, idx)
                    result.symbols.append(sym)
                    cur.eat_to_line_end()
            elif t.value == "class":
                idx = cur.i
                cur.next()
                cur.skip_punct()
                name_t = cur.peek()
                if name_t and name_t.kind == "ident":
                    while class_stack and name_t.col <= class_stack[-1][1]:
                        class_stack.pop()
                    cur.next()
                    sym = Symbol(name_t.value, KIND_CLASS, name_t.line, name_t.col, "class " + name_t.value)
                    _attach_doc(sym, raw, idx)
                    result.symbols.append(sym)
                    class_stack.append((name_t.value, name_t.col))
                cur.eat_to_line_end()
            elif t.value == "import":
                cur.next()
                parts: List[str] = []
                while not cur.at_end():
                    nt = cur.peek()
                    if nt.kind == "ident":
                        parts.append(nt.value)
                        cur.next()
                    elif nt.kind == "punct" and nt.value == ".":
                        cur.next()
                    elif nt.kind == "keyword" and nt.value == "as":
                        cur.next()
                        alias = cur.peek()
                        if alias and alias.kind == "ident":
                            if parts:
                                parts[-1] = alias.value
                            cur.next()
                    else:
                        break
                if parts:
                    result.imports.append(Import(".".join(parts), "import " + ".".join(parts), t.line))
            elif t.value == "from":
                cur.next()
                start_line = t.line
                parts = []
                if cur.peek() and cur.peek().kind == "ident":
                    while not cur.at_end():
                        nt = cur.peek()
                        if nt.kind == "ident":
                            parts.append(nt.value)
                            cur.next()
                        elif nt.kind == "punct" and nt.value == ".":
                            cur.next()
                        elif nt.kind == "keyword" and nt.value == "import":
                            cur.next()
                            break
                        else:
                            break
                module = ".".join(parts)
                if module:
                    targets: List[str] = []
                    while not cur.at_end():
                        nt = cur.peek()
                        if nt.kind == "ident":
                            targets.append(nt.value)
                            cur.next()
                        elif nt.kind == "keyword" and nt.value == "as":
                            cur.next()
                            alias = cur.peek()
                            if alias and alias.kind == "ident" and targets:
                                targets[-1] = alias.value
                            cur.next()
                        elif nt.kind == "punct" and nt.value == ",":
                            cur.next()
                        elif nt.kind == "punct" and nt.value in ("(", ")"):
                            cur.next()
                        elif nt.kind == "punct" and nt.value == ":":
                            cur.next()
                            break
                        elif nt.kind == "keyword" and nt.value == "as":
                            cur.next()
                        else:
                            break
                    for tg in (targets or [module]):
                        result.imports.append(Import(tg, f"from {module} import {tg}", start_line))
        if cur.i == _probe:  # guarantee progress on unmatched tokens
            cur.next()
    return result


def extract_javascript(text: str, language: str) -> ExtractionResult:
    result = ExtractionResult()
    raw = tokenize(text, language)
    tokens = significant_tokens(raw)
    cur = _Cursor(tokens)
    class_depth = _ClassDepth()
    prev_export = False

    def is_arrow_function() -> bool:
        """After seeing `=`, decide if this ctor is an arrow function."""
        save = cur.i
        # cursor is parked exactly on `(` (already consumed the `=`); no-op
        # when the arrow has a bare parameter (`x => x`) instead of `(x) =>`.
        cur.eat_balanced_parens()
        # `=>` lexes as two punct tokens (`=` `>`)
        a1 = cur.peek()
        a2 = cur.peek(1)
        arrow = (
            a1 is not None and a1.kind == "punct" and a1.value == "="
            and a2 is not None and a2.kind == "punct" and a2.value == ">"
        )
        cur.i = save
        return arrow

    while not cur.at_end():
        t = cur.peek()
        if t is None:
            break
        if t.kind == "keyword":
            if t.value == "export":
                prev_export = True
                cur.next()
                continue
            if t.value == "default" and prev_export:
                prev_export = False
                cur.next()
                continue
            if t.value == "class":
                idx = cur.i
                cur.next()
                cur.skip_punct()
                name_t = cur.peek()
                modifier = ""
                if name_t and name_t.kind == "punct" and name_t.value == "{":
                    name_t = None
                    modifier = "(anonymous)"
                if name_t and name_t.kind == "ident":
                    cur.next()
                    sym = Symbol(name_t.value, KIND_CLASS, name_t.line, name_t.col, "class " + name_t.value)
                    _attach_doc(sym, raw, idx)
                    result.symbols.append(sym)
                    # find opening brace to start depth tracking
                    while not cur.at_end() and not (
                        cur.peek().kind == "punct" and cur.peek().value == "{"
                    ):
                        cur.next()
                    if cur.match_punct("{"):
                        class_depth.on_punct("{")
                prev_export = False
                continue
            if t.value == "function":
                idx = cur.i
                cur.next()
                cur.skip()
                name_t = cur.peek()
                if name_t and name_t.kind == "ident":
                    cur.next()
                    sig = ""
                    if cur.match_punct("("):
                        sig = cur.signature_after_paren()
                    kind = KIND_METHOD if class_depth.inside else KIND_FUNCTION
                    parent = ""
                    sym = Symbol(name_t.value, kind, name_t.line, name_t.col, f"function {name_t.value}{sig}", parent=parent)
                    _attach_doc(sym, raw, idx)
                    result.symbols.append(sym)
                    quarter = cur.eat_to_line_end()
                prev_export = False
                continue
            if t.value in ("const", "let", "var"):
                idx = cur.i
                cur.next()
                cur.skip()
                name_t = cur.peek()
                if name_t and name_t.kind == "ident":
                    save = cur.i
                    cur.next()
                    if cur.match_punct("="):
                        if is_arrow_function():
                            sig = ""
                            sym = Symbol(
                                name_t.value,
                                KIND_METHOD if class_depth.inside else KIND_FUNCTION,
                                name_t.line,
                                name_t.col,
                                f"{name_t.value} = ...",
                            )
                            _attach_doc(sym, raw, idx)
                            result.symbols.append(sym)
                        else:
                            # maybe a `const x = function`
                            nxt = cur.peek()
                            if nxt and nxt.kind == "keyword" and nxt.value == "function":
                                sym = Symbol(
                                    name_t.value,
                                    KIND_FUNCTION,
                                    name_t.line,
                                    name_t.col,
                                    f"{name_t.value} = function",
                                )
                                result.symbols.append(sym)
                            else:
                                result.symbols.append(
                                    Symbol(name_t.value, KIND_CONST, name_t.line, name_t.col, f"{name_t.value} = ...")
                                )
                    else:
                        cur.i = save
                        cur.next()
                prev_export = False
                continue
            if t.value == "interface":
                cur.next()
                name_t = cur.peek()
                if name_t and name_t.kind == "ident":
                    sym = Symbol(name_t.value, KIND_INTERFACE, name_t.line, name_t.col, "interface " + name_t.value)
                    result.symbols.append(sym)
                    cur.next()
                continue
            if t.value == "type" and language.startswith("typescript"):
                cur.next()
                name_t = cur.peek()
                if name_t and name_t.kind == "ident":
                    sym = Symbol(name_t.value, KIND_TYPE, name_t.line, name_t.col, f"type {name_t.value} =")
                    result.symbols.append(sym)
                    cur.next()
                continue
            if t.value == "import":
                cur.next()
                # import x from 'y' / import {a, b} from 'y' / import 'side-effect'
                first = cur.peek()
                if first:
                    if first.kind == "string":
                        result.imports.append(Import(first.value, "import " + first.value, first.line))
                    elif first.kind == "punct" and first.value in ("{", "*"):
                        depth = 0
                        targets: List[str] = []
                        while not cur.at_end():
                            nt = cur.next()
                            if nt.kind == "punct" and nt.value in ("{", "[", "("):
                                depth += 1
                            elif nt.kind == "punct" and nt.value in ("}", "]", ")"):
                                depth -= 1
                                if depth == 0:
                                    break
                            elif nt.kind == "ident":
                                targets.append(nt.value)
                            elif nt.kind == "keyword" and nt.value == "from":
                                break
                        nxt = cur.peek()
                        if nxt and nxt.kind == "string":
                            for tg in (targets or ["*"]):
                                result.imports.append(Import(nxt.value, f"from {nxt.value}", nxt.line))
                                break
                        else:
                            src = nxt.value if nxt else "*"
                            for tg in (targets or ["*"]):
                                result.imports.append(Import(src, f"import {tg}", first.line))
                    elif first.kind == "ident":
                        cur.next()
                        nxt = cur.peek()
                        if nxt and nxt.kind == "string":
                            result.imports.append(Import(nxt.value, f"from {nxt.value}", nxt.line))
                prev_export = False
                continue
            if t.value == "async":
                cur.next()
                nxt = cur.peek()
                if nxt and nxt.kind == "keyword" and nxt.value == "function":
                    idx = cur.i
                    cur.next()
                    cur.skip()
                    name_t = cur.peek()
                    if name_t and name_t.kind == "ident":
                        cur.next()
                        sig = ""
                        if cur.match_punct("("):
                            sig = cur.signature_after_paren()
                        sym = Symbol(
                            name_t.value,
                            KIND_METHOD if class_depth.inside else KIND_FUNCTION,
                            name_t.line,
                            name_t.col,
                            f"async function {name_t.value}{sig}",
                        )
                        _attach_doc(sym, raw, idx)
                        result.symbols.append(sym)
                prev_export = False
                continue
        elif t.kind == "ident":
            # ES class methods: `name(args) {` inside a class body
            nxt = cur.peek(1)
            if class_depth.inside and nxt and nxt.kind == "punct" and nxt.value == "(":
                idx = cur.i
                name = t.value
                cur.next()
                sig = ""
                if cur.match_punct("("):
                    sig = cur.signature_after_paren()
                sym = Symbol(name, KIND_METHOD, t.line, t.col, f"{name}{sig}")
                _attach_doc(sym, raw, idx)
                result.symbols.append(sym)
                continue
            cur.next()
        elif t.kind == "punct":
            class_depth.on_punct(t.value)
        # consume
        cur.next()
    return result


def extract_rust(text: str) -> ExtractionResult:
    result = ExtractionResult()
    raw = tokenize(text, "rust")
    tokens = significant_tokens(raw)
    cur = _Cursor(tokens)
    block_stack: List[str] = []

    def parent_kind() -> str:
        for kind in reversed(block_stack):
            if kind in (KIND_IMPL, KIND_STRUCT, KIND_ENUM, KIND_TRAIT):
                return KIND_METHOD
        return KIND_FUNCTION

    while not cur.at_end():
        t = cur.peek()
        if t is None:
            break
        if t.kind == "keyword":
            if t.value in ("fn",):
                idx = cur.i
                cur.next()
                name_t = cur.peek()
                if name_t and name_t.kind == "ident":
                    cur.next()
                    sig = ""
                    if cur.match_punct("("):
                        sig = cur.signature_after_paren()
                    kind = parent_kind()
                    sym = Symbol(name_t.value, kind, name_t.line, name_t.col, f"fn {name_t.value}{sig}")
                    _attach_doc(sym, raw, idx)
                    result.symbols.append(sym)
            elif t.value in ("struct", "enum", "trait"):
                kind = {"struct": KIND_STRUCT, "enum": KIND_ENUM, "trait": KIND_TRAIT}[t.value]
                idx = cur.i
                cur.next()
                cur.skip_punct()
                name_t = cur.peek()
                if name_t and name_t.kind == "ident":
                    cur.next()
                    sym = Symbol(name_t.value, kind, name_t.line, name_t.col, f"{t.value} {name_t.value}")
                    _attach_doc(sym, raw, idx)
                    result.symbols.append(sym)
                    while not cur.at_end() and not (
                        cur.peek().kind == "punct" and cur.peek().value == "{"
                    ):
                        cur.next()
                    if cur.match_punct("{"):
                        block_stack.append(kind)
            elif t.value == "impl":
                idx = cur.i
                cur.next()
                cur.skip()
                first = cur.peek()
                if first and first.kind in ("ident", "keyword"):
                    target = first.value
                    cur.next()
                    if cur.peek() and cur.peek().kind == "keyword" and cur.peek().value == "for":
                        cur.next()
                        tgt2 = cur.peek()
                        if tgt2 and tgt2.kind in ("ident", "keyword"):
                            target = f"{target} for {tgt2.value}"
                            cur.next()
                    sym = Symbol(target, KIND_IMPL, first.line, first.col, f"impl {target}")
                    _attach_doc(sym, raw, idx)
                    result.symbols.append(sym)
                    while not cur.at_end() and not (
                        cur.peek().kind == "punct" and cur.peek().value == "{"
                    ):
                        cur.next()
                    if cur.match_punct("{"):
                        block_stack.append(KIND_IMPL)
            elif t.value == "mod":
                cur.next()
                name_t = cur.peek()
                if name_t and name_t.kind == "ident":
                    sym = Symbol(name_t.value, KIND_MODULE, name_t.line, name_t.col, f"mod {name_t.value}")
                    result.symbols.append(sym)
                    cur.next()
            elif t.value == "type":
                cur.next()
                name_t = cur.peek()
                if name_t and name_t.kind == "ident":
                    sym = Symbol(name_t.value, KIND_TYPE, name_t.line, name_t.col, f"type {name_t.value} =")
                    result.symbols.append(sym)
                    cur.next()
            elif t.value == "use":
                cur.next()
                first = cur.peek()
                if first and first.kind in ("ident", "keyword"):
                    parts = [first.value]
                    cur.next()
                    while not cur.at_end():
                        nt = cur.peek()
                        if nt.kind == "punct" and nt.value == "::":
                            cur.next()
                            n2 = cur.peek()
                            if n2 and n2.kind in ("ident", "keyword"):
                                parts.append(n2.value)
                                cur.next()
                            else:
                                break
                        else:
                            break
                    result.imports.append(Import("::".join(parts), "use " + "::".join(parts), first.line))
            elif t.value == "const":
                cur.next()
                name_t = cur.peek()
                if name_t and name_t.kind == "ident":
                    sym = Symbol(name_t.value, KIND_CONST, name_t.line, name_t.col, f"const {name_t.value}")
                    result.symbols.append(sym)
                    cur.next()
        elif t.kind == "punct" and t.value == "}":
            if block_stack:
                block_stack.pop()
        cur.next()
    return result


def extract_c_family(text: str, language: str) -> ExtractionResult:
    """C / C++ / Java share the shape `[modifiers] [ret-type] name(args)`."""
    result = ExtractionResult()
    raw = tokenize(text, language)
    tokens = significant_tokens(raw)
    cur = _Cursor(tokens)
    block_stack: List[str] = []
    java_keywords_skip = {
        "if", "while", "for", "switch", "catch", "return", "new", "sizeof",
        "decltype", "extends", "super", "this", "assert", "throw", "case",
    }

    def inside_type() -> bool:
        return bool(block_stack)

    while not cur.at_end():
        t = cur.peek()
        if t is None:
            break
        if t.kind == "keyword":
            if t.value in ("class", "struct", "enum", "interface", "namespace"):
                kind = {"class": KIND_CLASS, "struct": KIND_STRUCT, "enum": KIND_ENUM,
                        "interface": KIND_INTERFACE, "namespace": KIND_MODULE}[t.value]
                idx = cur.i
                cur.next()
                cur.skip_punct()
                name_t = cur.peek()
                if name_t and name_t.kind == "ident":
                    cur.next()
                    sym = Symbol(name_t.value, kind, name_t.line, name_t.col, f"{t.value} {name_t.value}")
                    _attach_doc(sym, raw, idx)
                    result.symbols.append(sym)
                    while not cur.at_end() and not (
                        cur.peek().kind == "punct" and cur.peek().value == "{"
                    ):
                        cur.next()
                    if cur.match_punct("{"):
                        block_stack.append(kind)
            elif t.value == "typedef":
                idx = cur.i
                cur.next()
                name_t = cur.peek()
                if name_t and name_t.kind == "ident":
                    cur.next()
                    sym = Symbol(name_t.value, KIND_TYPE, name_t.line, name_t.col, f"typedef {name_t.value}")
                    _attach_doc(sym, raw, idx)
                    result.symbols.append(sym)
            elif t.value in ("import", "package") and language == "java":
                cur.next()
                parts: List[str] = []
                while not cur.at_end():
                    nt = cur.peek()
                    if nt.kind == "ident":
                        parts.append(nt.value)
                        cur.next()
                    elif nt.kind == "punct" and nt.value == ".":
                        cur.next()
                    else:
                        break
                if parts:
                    target = ".".join(parts)
                    if t.value == "import":
                        result.imports.append(Import(target, f"import {target}", cur.tokens[max(0, cur.i - 1)].line))
                    else:
                        result.symbols.append(
                            Symbol(target, KIND_MODULE, cur.tokens[max(0, cur.i - 1)].line, 0, f"package {target}")
                        )
            elif t.value == "using" and language == "cpp":
                nxt = cur.peek(1)
                if nxt and nxt.kind == "keyword" and nxt.value == "namespace":
                    idx = cur.i
                    cur.next()
                    cur.next()
                    name_t = cur.peek()
                    if name_t and name_t.kind == "ident":
                        cur.next()
                        sym = Symbol(name_t.value, KIND_MODULE, name_t.line, name_t.col,
                                     f"using namespace {name_t.value}")
                        _attach_doc(sym, raw, idx)
                        result.symbols.append(sym)
            # consume keyword token
            cur.next()
            continue

        if t.kind == "ident":
            nxt = cur.peek(1)
            prev = cur.peek(-1) if cur.i > 0 else None
            if nxt and nxt.kind == "punct" and nxt.value == "(":
                # lookalike-call guard: `foo(...)` after `) ] } -> => . * & , ; (` is a call
                looks_like_call = prev is not None and (
                    (prev.kind == "punct" and prev.value in (")", "]", "}", ">", "->", ".", ",", ";", "(", "*", "&"))
                    or (prev.kind == "keyword" and prev.value in java_keywords_skip)
                )
                if not looks_like_call:
                    if language == "java" and prev and prev.kind == "ident":
                        # `Type name(` → the second ident is the method; the first
                        # ident was a return type we already emitted as its own
                        # candidate. Treat consecutive-ident case as a call site
                        # unless the previous ident was `new`.
                        looks_like_call = True
                    if not looks_like_call:
                        idx = cur.i
                        name = t.value
                        cur.next()
                        sig = ""
                        if cur.match_punct("("):
                            sig = cur.signature_after_paren()
                        kind = KIND_METHOD if inside_type() else KIND_FUNCTION
                        sym = Symbol(name, kind, t.line, t.col, f"{name}{sig}")
                        _attach_doc(sym, raw, idx)
                        result.symbols.append(sym)
                        continue
        elif t.kind == "punct":
            if t.value == "}":
                if block_stack:
                    block_stack.pop()
        cur.next()
    return result


def extract_go(text: str) -> ExtractionResult:
    result = ExtractionResult()
    raw = tokenize(text, "go")
    tokens = significant_tokens(raw)
    cur = _Cursor(tokens)
    while not cur.at_end():
        _probe = cur.i
        t = cur.peek()
        if t is None:
            break
        if t.kind == "keyword":
            if t.value == "func":
                idx = cur.i
                cur.next()
                # receiver form: func (r Recv) Name(...)
                if cur.peek() and cur.peek().kind == "punct" and cur.peek().value == "(":
                    cur.eat_balanced_parens()
                name_t = cur.peek()
                if name_t and name_t.kind == "ident":
                    cur.next()
                    sig = ""
                    if cur.match_punct("("):
                        sig = cur.signature_after_paren()
                    sym = Symbol(name_t.value, KIND_FUNCTION, name_t.line, name_t.col, f"func {name_t.value}{sig}")
                    _attach_doc(sym, raw, idx)
                    result.symbols.append(sym)
            elif t.value == "type":
                idx = cur.i
                cur.next()
                name_t = cur.peek()
                if name_t and name_t.kind == "ident":
                    cur.next()
                    kind = KIND_TYPE
                    nxt = cur.peek()
                    if nxt and nxt.kind == "keyword" and nxt.value in ("struct", "interface"):
                        kind = {"struct": KIND_STRUCT, "interface": KIND_INTERFACE}[nxt.value]
                    sym = Symbol(name_t.value, kind, name_t.line, name_t.col, f"type {name_t.value}")
                    _attach_doc(sym, raw, idx)
                    result.symbols.append(sym)
            elif t.value == "package":
                cur.next()
                name_t = cur.peek()
                if name_t and name_t.kind == "ident":
                    sym = Symbol(name_t.value, KIND_MODULE, name_t.line, name_t.col, f"package {name_t.value}")
                    result.symbols.append(sym)
                    cur.next()
            elif t.value == "import":
                cur.next()
                first = cur.peek()
                if first and first.kind == "string":
                    target = first.value.strip('"').strip("'")
                    result.imports.append(Import(target, f"import {target}", first.line))
                    cur.next()
                elif first and first.kind == "punct" and first.value == "(":
                    while not cur.at_end():
                        nt = cur.next()
                        if nt.kind == "string":
                            target = nt.value.strip('"').strip("'")
                            result.imports.append(Import(target, f"import {target}", nt.line))
                        elif nt.kind == "punct" and nt.value == ")":
                            break
        if cur.i == _probe:  # guarantee progress on unmatched tokens
            cur.next()
    return result


def extract_ruby(text: str) -> ExtractionResult:
    result = ExtractionResult()
    raw = tokenize(text, "ruby")
    tokens = significant_tokens(raw)
    cur = _Cursor(tokens)
    module_stack: List[str] = []
    while not cur.at_end():
        _probe = cur.i
        t = cur.peek()
        if t is None:
            break
        if t.kind == "keyword":
            if t.value == "def":
                idx = cur.i
                cur.next()
                name_t = cur.peek()
                if name_t and name_t.kind == "ident":
                    cur.next()
                    sig = ""
                    if cur.match_punct("("):
                        sig = cur.signature_after_paren()
                    sym = Symbol(name_t.value, KIND_METHOD if module_stack else KIND_FUNCTION,
                                 name_t.line, name_t.col, f"def {name_t.value}{sig}")
                    _attach_doc(sym, raw, idx)
                    result.symbols.append(sym)
            elif t.value == "class":
                cur.next()
                name_t = cur.peek()
                if name_t and name_t.kind == "ident":
                    sym = Symbol(name_t.value, KIND_CLASS, name_t.line, name_t.col, f"class {name_t.value}")
                    result.symbols.append(sym)
                    cur.next()
            elif t.value == "module":
                cur.next()
                name_t = cur.peek()
                if name_t and name_t.kind == "ident":
                    sym = Symbol(name_t.value, KIND_MODULE, name_t.line, name_t.col, f"module {name_t.value}")
                    result.symbols.append(sym)
                    module_stack.append(name_t.value)
                    cur.next()
            elif t.value == "require":
                cur.next()
                str_t = cur.peek()
                if str_t and str_t.kind == "string":
                    result.imports.append(Import(str_t.value.strip("'\""), f"require {str_t.value}", str_t.line))
                    cur.next()
        if cur.i == _probe:  # guarantee progress on unmatched tokens
            cur.next()
    return result


def extract_shell(text: str) -> ExtractionResult:
    result = ExtractionResult()
    raw = tokenize(text, "shell")
    tokens = significant_tokens(raw)
    cur = _Cursor(tokens)
    while not cur.at_end():
        t = cur.peek()
        if t is None:
            break
        if t.kind == "keyword" and t.value == "function":
            cur.next()
            name_t = cur.peek()
            if name_t and name_t.kind == "ident":
                sym = Symbol(name_t.value, KIND_FUNCTION, name_t.line, name_t.col, f"function {name_t.value}")
                result.symbols.append(sym)
                cur.next()
        elif t.kind == "ident":
            nxt = cur.peek(1)
            nxt2 = cur.peek(2)
            if (
                nxt and nxt.kind == "punct" and nxt.value == "("
                and nxt2 and nxt2.kind == "punct" and nxt2.value == ")"
            ):
                sym = Symbol(t.value, KIND_FUNCTION, t.line, t.col, f"{t.value}()")
                result.symbols.append(sym)
                cur.next()
                cur.next()
                cur.next()
                continue
            cur.next()
        else:
            cur.next()
    return result


def extract_markdown(text: str) -> ExtractionResult:
    result = ExtractionResult()
    for i, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("#"):
            level = len(stripped) - len(stripped.lstrip("#"))
            title = stripped[level:].strip()
            if title and level <= 4:
                result.symbols.append(Symbol(title, KIND_HEADING, i, 0, "#" * level + " " + title))
        elif stripped.startswith("```"):
            pass
    return result


_EXTRACTORS = {
    "python": extract_python,
    "javascript": lambda t: extract_javascript(t, "javascript"),
    "typescript": lambda t: extract_javascript(t, "typescript"),
    "rust": extract_rust,
    "c": lambda t: extract_c_family(t, "c"),
    "cpp": lambda t: extract_c_family(t, "cpp"),
    "java": lambda t: extract_c_family(t, "java"),
    "go": extract_go,
    "ruby": extract_ruby,
    "shell": extract_shell,
    "markdown": extract_markdown,
}


def extract(text: str, language: Optional[str]) -> ExtractionResult:
    """Extract symbols/imports from source text.

    Returns an empty :class:`ExtractionResult` when the language has no
    extractor (JSON, YAML, ...) — those files are still indexed for search.
    """
    if not language or language == "json":
        return ExtractionResult()
    fn = _EXTRACTORS.get(language)
    if fn is None:
        return ExtractionResult()
    try:
        return fn(text)
    except Exception:
        # A strange file must never kill the whole index run.
        return ExtractionResult()


def extract_cursor_c_family_bugfix(tokens: List[Token]) -> None:  # pragma: no cover
    """No-op placeholder to keep the API stable across versions."""
    return None