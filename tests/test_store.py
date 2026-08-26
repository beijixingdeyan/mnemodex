import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from base import TempDirTestCase

from mnemodex.store import MemoryStore, new_entry, KINDS
from mnemodex.memory import Memory, autocategorize


class StoreTest(TempDirTestCase):
    def store(self):
        return MemoryStore(os.path.join(self.tmp, ".mnemodex"))

    def test_append_and_read(self):
        s = self.store()
        s.append(new_entry("decision one", "decision", tags=["arch"]))
        s.append(new_entry("gotcha two", "gotcha"))
        entries = s.read()
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0]["kind"], "decision")
        self.assertEqual(entries[0]["tags"], ["arch"])

    def test_gc_dedupe_and_ttl(self):
        s = self.store()
        import time

        now = int(time.time())
        dup = new_entry("same text", "note")
        s.append(new_entry("same text", "note"))
        s.append(dup)
        s.append(new_entry("expired", "note", ttl_days=1))
        # rewrite the expired entry with an old timestamp to force expiry
        entries = s.read()
        for e in entries:
            if e["text"] == "expired":
                e["created_at"] = now - 3 * 86400
                e["ttl_days"] = 1
        s.replace(entries)
        report = s.gc()
        self.assertGreaterEqual(report["expired"], 1)
        self.assertGreaterEqual(report["deduped"], 1)
        final = s.read()
        texts = [e["text"] for e in final]
        self.assertEqual(texts.count("same text"), 1)
        self.assertNotIn("expired", texts)

    def test_corrupt_line_raises(self):
        s = self.store()
        os.makedirs(self.store().store_dir or self.tmp, exist_ok=True)
        path = s.path
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            fh.write("{not json}\n")
        from mnemodex.errors import StoreCorruptError

        with self.assertRaises(StoreCorruptError):
            s.read()


class MemoryTest(TempDirTestCase):
    def mem(self):
        return Memory(os.path.join(self.tmp, ".mnemodex"))

    def test_autocategorize(self):
        self.assertEqual(autocategorize("we decided to cache tokens"), "decision")
        self.assertEqual(autocategorize("gotcha: cookie hashes change"), "gotcha")
        self.assertEqual(autocategorize("use faster index instead"), "tip")
        self.assertEqual(autocategorize("nothing special here"), "note")

    def test_add_dedupe(self):
        m = self.mem()
        first = m.add("cache tokens for five minutes", tags=["a", "b"])
        second = m.add("cache tokens for five minutes", tags=["a", "b"])
        self.assertFalse(first["duplicate"])
        self.assertTrue(second["duplicate"])
        self.assertEqual(m.store.count(), 1)

    def test_recall_ranking(self):
        m = self.mem()
        m.add("auth tokens are cached for five minutes", kind="decision")
        m.add("cookie hashes change per release", kind="gotcha")
        hits = m.recall("tokens cache", limit=5)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["kind"], "decision")

    def test_forget_and_forget_matching(self):
        m = self.mem()
        r = m.add("something to forget", kind="note")
        self.assertTrue(m.forget(r["entry"]["id"]))
        self.assertFalse(m.forget(r["entry"]["id"]))
        m.add("keep me", kind="note")
        m.add("drop me too", kind="note")
        removed = m.forget_matching("drop")
        self.assertEqual(removed, 1)

    def test_export_markdown(self):
        m = self.mem()
        m.add("tokens cached for five minutes", kind="decision", tags=["cache"])
        md = m.export_markdown()
        self.assertIn("# Repository Memory", md)
        self.assertIn("Decision", md)
        self.assertIn("tokens cached", md)

    def test_kind_validation(self):
        m = self.mem()
        r = m.add("weird kind", kind="bogus")
        self.assertEqual(r["entry"]["kind"], "note")


if __name__ == "__main__":
    unittest.main()