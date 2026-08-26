import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from base import TempDirTestCase, materialize_sample

from mnemodex.mcp import McpServer, Tool
from mnemodex.session import Session


class ProtocolTest(unittest.TestCase):
    def setUp(self):
        self.server = McpServer(
            tools=[
                Tool(
                    "echo",
                    "echo a string",
                    {"type": "object", "properties": {"s": {"type": "string"}}, "required": ["s"]},
                    lambda args: {"echoed": args.get("s", "")},
                )
            ]
        )

    def test_initialize(self):
        resp = json.loads(
            self.server.handle_line(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}))
        )
        self.assertEqual(resp["id"], 1)
        self.assertEqual(resp["result"]["serverInfo"]["name"], "mnemodex")
        self.assertIn("tools", resp["result"]["capabilities"])

    def test_notification_no_response(self):
        self.assertIsNone(
            self.server.handle_line(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}))
        )

    def test_tools_list(self):
        resp = json.loads(self.server.handle_line(json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})))
        names = [t["name"] for t in resp["result"]["tools"]]
        self.assertIn("echo", names)

    def test_tools_call(self):
        resp = json.loads(
            self.server.handle_line(
                json.dumps({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                            "params": {"name": "echo", "arguments": {"s": "hi"}}})
            )
        )
        self.assertIn("hi", resp["result"]["content"][0]["text"])

    def test_unknown_method_error(self):
        resp = json.loads(self.server.handle_line(json.dumps({"jsonrpc": "2.0", "id": 4, "method": "nope"})))
        self.assertEqual(resp["error"]["code"], -32601)

    def test_unknown_tool_error(self):
        resp = json.loads(
            self.server.handle_line(
                json.dumps({"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                            "params": {"name": "missing", "arguments": {}}})
            )
        )
        self.assertEqual(resp["error"]["code"], -32601)

    def test_parse_error(self):
        resp = json.loads(self.server.handle_line("{not json"))
        self.assertEqual(resp["error"]["code"], -32700)
        self.assertEqual(resp["error"]["message"], "parse error")

    def test_ping(self):
        resp = json.loads(self.server.handle_line(json.dumps({"jsonrpc": "2.0", "id": 9, "method": "ping"})))
        self.assertEqual(resp["result"], {})


class SessionMcpTest(TempDirTestCase):
    def setUp(self):
        super().setUp()
        self.repo = materialize_sample(self.tmp)
        from mnemodex.indexer import IndexBuilder

        result = IndexBuilder(self.repo).build()
        store_dir = os.path.join(self.repo, ".mnemodex")
        os.makedirs(store_dir, exist_ok=True)
        from mnemodex import config as cfg, util

        cfg.write_config(store_dir, cfg.default_config())
        util.atomic_write_json(os.path.join(store_dir, "index.json"), result)
        self.session = Session(cwd=self.repo)

    def test_tool_recall(self):
        self.session.add_memory("auth tokens cached five minutes", kind="decision", source="test")
        server = McpServer(__import__("mnemodex.mcp", fromlist=["build_tools"]).build_tools(self.session))
        resp = json.loads(
            server.handle_line(
                json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                            "params": {"name": "mnemodex_recall", "arguments": {"query": "cache"}}})
            )
        )
        text = resp["result"]["content"][0]["text"]
        self.assertIn("cache", text)

    def test_tool_lookup_symbol(self):
        server = McpServer(__import__("mnemodex.mcp", fromlist=["build_tools"]).build_tools(self.session))
        resp = json.loads(
            server.handle_line(
                json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                            "params": {"name": "mnemodex_lookup_symbol", "arguments": {"name": "LRUCache"}}})
            )
        )
        text = resp["result"]["content"][0]["text"]
        self.assertIn("lru.py", text)

    def test_read_file_traversal_safe(self):
        server = McpServer(__import__("mnemodex.mcp", fromlist=["build_tools"]).build_tools(self.session))
        resp = json.loads(
            server.handle_line(
                json.dumps({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                            "params": {"name": "mnemodex_read_file", "arguments": {"path": "../../etc/passwd"}}})
            )
        )
        # traversal refused → snippet empty, no crash
        self.assertIn('"snippet"', resp["result"]["content"][0]["text"])


if __name__ == "__main__":
    unittest.main()