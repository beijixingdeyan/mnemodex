import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mnemodex import util


class SplitWordsTest(unittest.TestCase):
    def test_simple(self):
        self.assertEqual(util.split_words("cache eviction"), ("cache", "eviction"))

    def test_stopwords(self):
        self.assertNotIn("the", util.split_words("the cache is the best"))
        self.assertIn("cache", util.split_words("the cache is the best"))

    def test_camel_and_snake(self):
        words = util.split_words("buildCacheEviction_cache")
        self.assertIn("build", words)
        self.assertIn("cache", words)
        self.assertIn("eviction", words)
        self.assertIn("cache", util.split_words("build_cache"))

    def test_symbols_split_out(self):
        self.assertNotIn("->", util.split_words("a -> b"))


class FingerprintTest(unittest.TestCase):
    def test_deterministic(self):
        a = util.token_fingerprint("we cache tokens for five minutes")
        b = util.token_fingerprint("we cache tokens for five minutes")
        self.assertEqual(a, b)

    def test_different(self):
        a = util.token_fingerprint("cache tokens five minutes")
        b = util.token_fingerprint("cookie hashes change per release")
        self.assertNotEqual(a, b)


class RepoRelativeTest(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(util.repo_relative("/repo/src/a.py", "/repo"), "src/a.py")
        self.assertEqual(util.repo_relative("/repo/a.py", "/repo"), "a.py")

    @unittest.skipUnless(os.name == "nt", "drive-letter paths only exist on Windows")
    def test_windows_drive_paths(self):
        self.assertEqual(util.repo_relative(r"E:\x\src\a.py", r"E:\x"), "src/a.py")
        self.assertEqual(util.repo_relative(r"E:\x\a.py", r"E:\x"), "a.py")

    def test_safe_join_rejects_traversal(self):
        with self.assertRaises(ValueError):
            util.safe_join("C:/repo", "../secret.txt")
        with self.assertRaises(ValueError):
            util.safe_join("C:/repo", "/etc/passwd")


class MiscTest(unittest.TestCase):
    def test_estimate_tokens(self):
        self.assertGreater(util.estimate_tokens("hello world " * 10), 1)

    def test_human_bytes(self):
        self.assertEqual(util.human_bytes(1024), "1.0 KB")

    def test_time_ago(self):
        self.assertEqual(util.time_ago(int(__import__("time").time())), "just now")

    def test_is_binary(self):
        tmp = os.path.join(__import__("tempfile").mkdtemp(), "bin")
        with open(tmp, "wb") as fh:
            fh.write(b"\x00\x01\x02\x03" * 100)
        self.assertTrue(util.is_binary(tmp))
        os.unlink(tmp)

    def test_atomic_write_json_roundtrip(self):
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "x.json")
            util.atomic_write_json(path, {"a": [1, 2], "b": "café"})
            self.assertEqual(util.read_json(path), {"a": [1, 2], "b": "café"})

    def test_file_lock(self):
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            lock = os.path.join(d, "l")
            with util.file_lock(lock):
                self.assertTrue(os.path.exists(lock + ".lock"))
            self.assertFalse(os.path.exists(lock + ".lock"))


if __name__ == "__main__":
    unittest.main()