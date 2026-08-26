import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mnemodex.symbols import extract as extract_fn


class PythonSymbolsTest(unittest.TestCase):
    def test_class_and_function(self):
        src = "class Foo:\n    def bar(self):\n        pass\n\ndef top():\n    pass\n"
        result = extract_fn(src, "python")
        names = {s.name: s.kind for s in result.symbols}
        self.assertEqual(names["Foo"], "class")
        self.assertEqual(names["bar"], "method")
        self.assertEqual(names["top"], "function")

    def test_imports(self):
        result = extract_fn("from src.cache.lru import LRUCache\nimport json", "python")
        targets = [i.target for i in result.imports]
        self.assertIn("LRUCache", targets)
        self.assertIn("json", targets)

    def test_module_docstring(self):
        result = extract_fn('"""module doc"""\nx = 1', "python")
        self.assertIn("module doc", result.module_doc)


class JavascriptSymbolsTest(unittest.TestCase):
    def test_functions_and_classes(self):
        src = """
export class Foo {
  greet(name) { return "hi"; }
}
export function bar() {}
const arrow = (x) => x * 2;
const plain = function () {};
const CONSTANT = 1;
"""
        result = extract_fn(src, "javascript")
        names = {s.name: s.kind for s in result.symbols}
        self.assertEqual(names["Foo"], "class")
        self.assertIn("greet", names)
        self.assertEqual(names["bar"], "function")
        self.assertEqual(names["arrow"], "function")
        self.assertEqual(names["plain"], "function")
        self.assertEqual(names["CONSTANT"], "const")

    def test_typescript_types(self):
        src = "interface Session { user: string; }\ntype ID = string;\nclass M {}\n"
        result = extract_fn(src, "typescript")
        names = {s.name: s.kind for s in result.symbols}
        self.assertEqual(names["Session"], "interface")
        self.assertEqual(names["ID"], "type")
        self.assertEqual(names["M"], "class")

    def test_import(self):
        result = extract_fn('import { a, b } from "./utils";', "javascript")
        self.assertGreaterEqual(len(result.imports), 1)


class RustSymbolsTest(unittest.TestCase):
    def test_items(self):
        src = """
pub fn fib(n: u64) -> u64 { n }
pub struct Counter { value: u64 }
pub enum Kind { A, B }
pub trait Speak { fn talk(&self); }
pub mod inner { pub fn x() {} }
impl Counter {
    pub fn new() -> Counter { Counter { value: 0 } }
}
pub const MAX: u64 = 100;
"""
        result = extract_fn(src, "rust")
        kinds = {s.name: s.kind for s in result.symbols}
        self.assertEqual(kinds["fib"], "function")
        self.assertTrue(any(s.name == "Counter" and s.kind == "struct" for s in result.symbols))
        self.assertEqual(kinds["Kind"], "enum")
        self.assertEqual(kinds["Speak"], "trait")
        self.assertEqual(kinds["inner"], "module")
        self.assertEqual(kinds["new"], "method")
        self.assertEqual(kinds["MAX"], "const")


class CSymbolsTest(unittest.TestCase):
    def test_c_functions(self):
        src = "int add(int a, int b) { return a + b; }\nstatic void helper(void) {}\n"
        result = extract_fn(src, "c")
        names = {s.name for s in result.symbols}
        self.assertIn("add", names)
        self.assertIn("helper", names)

    def test_cpp_class(self):
        src = "class Widget { public: int size() const; };"
        result = extract_fn(src, "cpp")
        names = {s.name: s.kind for s in result.symbols}
        self.assertEqual(names["Widget"], "class")


class JavaSymbolsTest(unittest.TestCase):
    def test_class_and_method(self):
        src = (
            "package store;\n"
            "public class App {\n"
            "  private int count = 0;\n"
            "  public int bump(String key) { return ++count; }\n"
            "}\n"
        )
        result = extract_fn(src, "java")
        kinds = {s.name: s.kind for s in result.symbols}
        self.assertEqual(kinds["App"], "class")
        self.assertEqual(kinds["bump"], "method")
        # no bogus call-site symbols from String key merging etc.
        self.assertNotIn("Integer", kinds)


class GoSymbolsTest(unittest.TestCase):
    def test_everything(self):
        src = """
package main

type Greeter struct { name string }

func NewGreeter(name string) *Greeter { return &Greeter{name} }
func (g *Greeter) Hello() string { return "hi" }

type Speaker interface { Hello() string }
"""
        result = extract_fn(src, "go")
        kinds = {s.name: s.kind for s in result.symbols}
        self.assertEqual(kinds["Greeter"], "struct")
        self.assertEqual(kinds["NewGreeter"], "function")
        self.assertEqual(kinds["Hello"], "function")
        self.assertEqual(kinds["Speaker"], "interface")

    def test_import(self):
        result = extract_fn('import "fmt"\n', "go")
        self.assertTrue(any(i.target == "fmt" for i in result.imports))


class MarkdownSymbolsTest(unittest.TestCase):
    def test_headings(self):
        result = extract_fn("# Title\n\n## Section\n### Sub\n", "markdown")
        titles = [s.name for s in result.symbols]
        self.assertEqual(titles, ["Title", "Section", "Sub"])


class UnknownLanguageTest(unittest.TestCase):
    def test_empty(self):
        result = extract_fn("completely unknown language", "klingon")
        self.assertEqual(result.symbols, [])
        self.assertEqual(result.imports, [])


if __name__ == "__main__":
    unittest.main()