import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mnemodex.gitignore import RepoIgnore, IncrementalIgnore


def gi(lines, base="."):
    g = RepoIgnore()
    g.add(base, lines)
    return g


class GitIgnoreBasics(unittest.TestCase):
    def test_comment_and_blank(self):
        g = gi(["# comment", "", "*.log"])
        self.assertTrue(g.ignored("x.log"))
        self.assertFalse(g.ignored("x.py"))

    def test_dir_only(self):
        g = gi(["build/"])
        self.assertTrue(g.ignored("build", is_dir=True))
        self.assertTrue(g.ignored("build/intermediate.o"))  # parent pruned, but rule matches dir
        self.assertFalse(g.ignored("buildfile"))

    def test_anchored(self):
        g = gi(["/root.txt"])
        self.assertTrue(g.ignored("root.txt"))
        self.assertFalse(g.ignored("sub/root.txt"))

    def test_negation(self):
        g = gi(["*.log", "!important.log"])
        self.assertTrue(g.ignored("x.log"))
        self.assertFalse(g.ignored("important.log"))

    def test_basename_any_depth(self):
        g = gi(["*.pyc"])
        self.assertTrue(g.ignored("a/b/c/mod.pyc"))

    def test_globstar_dir(self):
        g = gi(["**/node_modules"])
        self.assertTrue(g.ignored("node_modules", is_dir=True))
        self.assertTrue(g.ignored("a/node_modules", is_dir=True))
        self.assertTrue(g.ignored("a/b/node_modules", is_dir=True))

    def test_dir_wildcard(self):
        g = gi(["doc/*.tmp"])
        self.assertTrue(g.ignored("doc/x.tmp"))
        self.assertFalse(g.ignored("doc/sub/x.tmp"))

    def test_question_and_class(self):
        g = gi(["file?.txt", "[ab].cfg"])
        self.assertTrue(g.ignored("file1.txt"))
        self.assertFalse(g.ignored("file12.txt"))
        self.assertTrue(g.ignored("a.cfg"))
        self.assertFalse(g.ignored("c.cfg"))

    def test_escaped_hash(self):
        g = gi(["\\#keep.me"])
        self.assertTrue(g.ignored("#keep.me"))

    def test_deeper_wins(self):
        # root says ignore tracked/**, nested .gitignore un-ignores one file
        g = RepoIgnore()
        g.add(".", ["tracked/**"])
        g.add("tracked", ["!keep.py", "*.py"])
        self.assertTrue(g.ignored("tracked/drop.py"))
        # keep.py: last matching rules = "!keep.py" (ignore) then "*.py" (ignore)
        # actually nested: '!keep.py' unignores, '*.py' re-ignores → ignored True
        self.assertTrue(g.ignored("tracked/keep.py"))


class NestedGitignoreFiles(unittest.TestCase):
    def test_build_from_tree(self):
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "pkg"))
            with open(os.path.join(d, ".gitignore"), "w") as fh:
                fh.write("*.log\n")
            with open(os.path.join(d, "pkg", ".gitignore"), "w") as fh:
                fh.write("!special.log\n")
            inc = IncrementalIgnore(d)
            self.assertTrue(inc.ignored("a.log"))
            self.assertFalse(inc.ignored("pkg/special.log"))
            self.assertTrue(inc.ignored("pkg/other.log"))

    def test_extra_patterns(self):
        inc = IncrementalIgnore(os.getcwd(), extra_patterns=["node_modules/"])
        # "node_modules/" must exist for the dir to be pruned, but pattern-only check:
        self.assertTrue(inc.ignored("node_modules", is_dir=True))


if __name__ == "__main__":
    unittest.main()