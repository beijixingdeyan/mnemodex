import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from base import TempDirTestCase, materialize_sample

from mnemodex.indexer import IndexBuilder, build_index
from mnemodex.graph import KnowledgeGraph, EDGE_IMPORT, EDGE_REF, file_id
from mnemodex.search import SearchIndex


class IndexerTest(TempDirTestCase):
    def setUp(self):
        super().setUp()
        self.repo = materialize_sample(self.tmp)
        self.result = build_index(self.repo, {"respect_gitignore": True})

    def test_summary_counts(self):
        summary = self.result["summary"]
        # 13 fixture files − node_modules/ignored.js − debug/output.log
        # (.gitignore) − hidden .gitignore = 10 indexed files
        self.assertEqual(summary["files"], 10)
        self.assertGreater(summary["symbols"], 20)
        languages = summary["languages"]
        self.assertIn("python", languages)
        self.assertIn("rust", languages)
        self.assertIn("go", languages)
        self.assertIn("java", languages)

    def test_index_contains_search_files(self):
        data = self.result["search"]
        files = [f["path"] for f in data["files"]]
        self.assertIn("src/api/auth.py", files)
        self.assertNotIn("node_modules/ignored.js", files)
        self.assertNotIn("debug/output.log", files)

    def test_graph_edges(self):
        graph = KnowledgeGraph.from_dict(self.result["graph"])
        # auth.py imports lru.py → import edge exists
        edges = graph.out_edges(file_id("src/api/auth.py"), EDGE_IMPORT)
        self.assertTrue(any(e.dst == file_id("src/cache/lru.py") for e in edges))

    def test_search_ranking(self):
        idx = SearchIndex.from_dict(self.result["search"])
        results = idx.search("cache eviction invalidate", limit=5)
        self.assertTrue(results)
        top = results[0].path
        self.assertIn("cache", top)

    def test_symbol_lookup(self):
        idx = SearchIndex.from_dict(self.result["search"])
        hits = idx.lookup_symbol("LRUCache")
        self.assertTrue(hits)
        self.assertEqual(hits[0].name, "LRUCache")

    def test_serialization_roundtrip(self):
        import json

        data = json.loads(json.dumps(self.result))
        idx = SearchIndex.from_dict(data["search"])
        self.assertEqual(len(idx), len(self.result["search"]["files"]))


class GraphAlgorithmsTest(TempDirTestCase):
    def _small_graph(self):
        g = KnowledgeGraph()
        for p in ("a.py", "b.py", "c.py"):
            g.add_node(file_id(p), "file", {"name": p})
        g.add_edge(file_id("a.py"), file_id("b.py"), EDGE_IMPORT)
        g.add_edge(file_id("b.py"), file_id("c.py"), EDGE_IMPORT)
        return g

    def test_shortest_path(self):
        g = self._small_graph()
        path = g.shortest_path(file_id("a.py"), file_id("c.py"))
        self.assertEqual(path, [file_id("a.py"), file_id("b.py"), file_id("c.py")])

    def test_components(self):
        g = self._small_graph()
        g.add_node(file_id("z.py"), "file", {"name": "z.py"})
        comps = g.connected_components()
        self.assertEqual(len(comps), 2)

    def test_page_rank_deterministic(self):
        g = self._small_graph()
        pr1 = g.page_rank(iterations=10)
        pr2 = g.page_rank(iterations=10)
        self.assertEqual(pr1, pr2)

    def test_k_hop(self):
        g = self._small_graph()
        dist = g.k_hop(file_id("a.py"), 2)
        self.assertEqual(dist[file_id("c.py")], 2)


class DotExportTest(TempDirTestCase):
    def test_dot(self):
        repo = materialize_sample(self.tmp)
        result = build_index(repo)
        graph = KnowledgeGraph.from_dict(result["graph"])
        dot = graph.to_dot()
        self.assertIn("digraph mnemodex", dot)
        self.assertIn("->", dot)


if __name__ == "__main__":
    unittest.main()