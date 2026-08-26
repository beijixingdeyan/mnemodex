import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from base import TempDirTestCase, materialize_sample, run_cli


class CliE2ETest(TempDirTestCase):
    def setUp(self):
        super().setUp()
        self.repo = materialize_sample(self.tmp)
        self.store = os.path.join(self.repo, ".mnemodex")

    def test_init(self):
        r = run_cli(["init"], cwd=self.repo)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.isdir(self.store))
        self.assertTrue(os.path.exists(os.path.join(self.store, "config.json")))
        # .gitignore gets the store entry
        with open(os.path.join(self.repo, ".gitignore")) as fh:
            self.assertIn(".mnemodex", fh.read())

    def test_index(self):
        run_cli(["init"], cwd=self.repo)
        r = run_cli(["index"], cwd=self.repo)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("files", r.stdout)
        idx_path = os.path.join(self.store, "index.json")
        self.assertTrue(os.path.exists(idx_path))

    def test_add_recall_flow(self):
        run_cli(["init"], cwd=self.repo)
        r = run_cli(["add", "auth tokens are cached for five minutes", "--kind", "decision", "--tags", "cache"], cwd=self.repo)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("remembered", r.stdout)
        r2 = run_cli(["recall", "cache"], cwd=self.repo)
        self.assertIn("tokens", r2.stdout)

    def test_ask_budget(self):
        run_cli(["init"], cwd=self.repo)
        run_cli(["add", "auth tokens are cached for five minutes", "--kind", "decision"], cwd=self.repo)
        run_cli(["index"], cwd=self.repo)
        r = run_cli(["ask", "cache", "--budget", "4000"], cwd=self.repo)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("context pack", r.stdout)

    def test_search(self):
        run_cli(["init"], cwd=self.repo)
        run_cli(["index"], cwd=self.repo)
        r = run_cli(["search", "lru", "--json"], cwd=self.repo)
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads(r.stdout)
        self.assertTrue(any("lru" in f["path"] for f in data))

    def test_symbol(self):
        run_cli(["init"], cwd=self.repo)
        run_cli(["index"], cwd=self.repo)
        r = run_cli(["symbol", "LRUCache"], cwd=self.repo)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("lru.py", r.stdout)

    def test_stats(self):
        run_cli(["init"], cwd=self.repo)
        r = run_cli(["stats", "--json"], cwd=self.repo)
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads(r.stdout)
        self.assertIn("memory", data)

    def test_export_agent_files(self):
        run_cli(["init"], cwd=self.repo)
        run_cli(["index"], cwd=self.repo)
        r = run_cli(["export", "agent", "--targets", "claude,codex"], cwd=self.repo)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.exists(os.path.join(self.repo, "CLAUDE.md")))
        self.assertTrue(os.path.exists(os.path.join(self.repo, "AGENTS.md")))

    def test_export_memory(self):
        run_cli(["init"], cwd=self.repo)
        run_cli(["add", "first fact"], cwd=self.repo)
        r = run_cli(["export", "memory", "--format", "md"], cwd=self.repo)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("first fact", r.stdout)

    def test_forget(self):
        run_cli(["init"], cwd=self.repo)
        run_cli(["add", "a doomed fact"], cwd=self.repo)
        r = run_cli(["forget", "--query", "doomed"], cwd=self.repo)
        self.assertEqual(r.returncode, 0, r.stderr)
        r2 = run_cli(["list"], cwd=self.repo)
        self.assertNotIn("doomed", r2.stdout)

    def test_gc(self):
        run_cli(["init"], cwd=self.repo)
        run_cli(["add", "a fact"], cwd=self.repo)
        r = run_cli(["gc"], cwd=self.repo)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_doctor(self):
        r = run_cli(["doctor"], cwd=self.repo)
        # not initialized → exit 1 with a hint on stdout, no traceback
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("init", r.stdout)
        self.assertNotIn("Traceback", r.stderr)

    def test_gif(self):
        run_cli(["init"], cwd=self.repo)
        out = os.path.join(self.tmp, "demo.gif")
        r = run_cli(["gif", "--out", out, "--frames", "40"], cwd=self.repo)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.exists(out))
        with open(out, "rb") as fh:
            head = fh.read(6)
        self.assertEqual(head, b"GIF89a")

    def test_not_initialized_error(self):
        r = run_cli(["stats"], cwd=self.tmp)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("mnemodex init", r.stderr)

    def test_version_subcommand(self):
        r = run_cli(["version"], cwd=self.repo)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("mnemodex", r.stdout)


if __name__ == "__main__":
    unittest.main()