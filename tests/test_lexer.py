import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mnemodex.lexer import Lexer, LexConfig, significant_tokens, tokenize


class PythonLexerTest(unittest.TestCase):
    def test_keywords_and_identifiers(self):
        tokens = tokenize("def foo(a, b):\n    return a + b", "python")
        kinds = [t.kind for t in tokens]
        self.assertIn("keyword", kinds)
        vals = [t.value for t in tokens]
        self.assertIn("foo", vals)
        self.assertIn("return", vals)

    def test_hash_comment_skipped(self):
        tokens = tokenize("x = 1  # note\n", "python")
        self.assertTrue(any(t.kind == "comment" for t in tokens))
        sig = significant_tokens(tokens)
        self.assertFalse(any(t.kind == "comment" for t in sig))

    def test_triple_quote_docstring(self):
        tokens = tokenize('"""module doc"""\nx = 1', "python")
        self.assertTrue(any(t.kind == "docstring" for t in tokens))

    def test_string_number(self):
        tokens = tokenize('s = "hi"; n = 0x1F; f = 1.5e3', "python")
        kinds = [t.kind for t in tokens]
        self.assertIn("string", kinds)
        self.assertIn("number", kinds)


class CLexerTest(unittest.TestCase):
    def test_block_comment(self):
        tokens = tokenize("int a; /* block */ int b;", "c")
        self.assertTrue(any(t.kind == "comment" and t.value.startswith("/*") for t in tokens))

    def test_line_comment(self):
        tokens = tokenize("a; // line\nb;", "cpp")
        self.assertTrue(any(t.kind == "comment" and "// line" in t.value for t in tokens))

    def test_rust_nested_comments(self):
        tokens = tokenize("/* outer /* inner */ still outer */", "rust")
        comments = [t for t in tokens if t.kind == "comment"]
        self.assertEqual(len(comments), 1)


class JsLexerTest(unittest.TestCase):
    def test_template_string(self):
        tokens = tokenize("const s = `hello ${name}`;", "javascript")
        self.assertTrue(any(t.kind == "string" and "`" in t.value for t in tokens))

    def test_hash_not_comment_in_js(self):
        # JS has no hash comments: `#` is punctuation
        tokens = tokenize("const x = 1; # not a comment", "javascript")
        values = [t.value for t in tokens]
        self.assertIn("#", values)


class PositionTest(unittest.TestCase):
    def test_line_numbers(self):
        tokens = tokenize("a\nb\nc", "python")
        idents = [t for t in tokens if t.kind == "ident"]
        self.assertEqual([t.line for t in idents], [1, 2, 3])

    def test_offset_monotonic(self):
        tokens = tokenize('x = "a b" + 12', "python")
        offsets = [t.offset for t in tokens]
        self.assertEqual(offsets, sorted(offsets))


class ConfigTest(unittest.TestCase):
    def test_for_language_unknown(self):
        cfg = LexConfig.for_language("not-a-real-language")
        self.assertEqual(cfg.line_comments, ())
        self.assertEqual(cfg.keywords, set())


if __name__ == "__main__":
    unittest.main()