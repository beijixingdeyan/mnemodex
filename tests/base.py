"""Shared fixtures for the test suite."""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PYTHON = sys.executable


def run_cli(args, cwd, env_extra=None, timeout=120):
    """Run `python -m mnemodex <args>` in *cwd*; returns CompletedProcess."""
    env = dict(os.environ)
    env["MNEMODEX_NO_COLOR"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONPATH"] = REPO_ROOT + os.pathsep + env.get("PYTHONPATH", "")
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [PYTHON, "-m", "mnemodex"] + list(args),
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


class TempDirTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, rel: str, content: str) -> str:
        path = os.path.join(self.tmp, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(content)
        return path


SAMPLE_REPO = {
    ".gitignore": "# sample\nnode_modules/\n*.log\n",
    "README.md": "# Demo repo\n\nThis is a sample repository for mnemodex tests.\n",
    "src/__init__.py": "",
    "src/cache/__init__.py": "",
    "src/cache/lru.py": '''
"""LRU cache for the demo project."""

DEFAULT_CAPACITY = 128


class LRUCache:
    """A dict+deque LRU cache."""

    def __init__(self, capacity: int = DEFAULT_CAPACITY):
        self.capacity = capacity
        self._items = {}

    def get(self, key):
        """Return the cached value or None."""
        return self._items.get(key)

    def put(self, key, value):
        self._items[key] = value


def invalidate_cache(cache):
    """Drop everything from a cache instance."""
    cache._items.clear()
''',
    "src/api/auth.py": '''
"""Auth endpoints."""

from src.cache.lru import LRUCache, invalidate_cache

tokens = LRUCache()


def login(username, password):
    token = "demo-" + username
    tokens.put(username, token)
    return token


def logout(username):
    invalidate_cache(tokens)
''',
    "web/app.ts": '''
import { LRUCache } from "./cache";
import { login } from "./auth";

export interface Session {
  user: string;
  token: string;
}

export class SessionManager {
  private sessions = new LRUCache<Session>();

  async create(user: string): Promise<Session> {
    const token = await login(user, "pw");
    const session: Session = { user, token };
    this.sessions.put(user, session);
    return session;
  }
}
''',
    "native/cache.c": '''
#include <stdlib.h>

typedef struct { int cap; int used; } cache_t;

cache_t *cache_new(int cap) {
    cache_t *c = malloc(sizeof(cache_t));
    if (c) { c->cap = cap; c->used = 0; }
    return c;
}

void cache_free(cache_t *c) { free(c); }
''',
    "native/lib.rs": '''
/// Fibonacci for the demo.
pub fn fib(n: u64) -> u64 {
    if n < 2 { n } else { fib(n - 1) + fib(n - 2) }
}

pub struct Counter { value: u64 }

impl Counter {
    pub fn new() -> Counter { Counter { value: 0 } }
    pub fn inc(&mut self) { self.value += 1; }
}
''',
    "cmd/main.go": '''
package main

import "fmt"

type Greeter struct{ name string }

func NewGreeter(name string) *Greeter { return &Greeter{name: name} }

func (g *Greeter) Hello() string { return "hello " + g.name }

func main() {
    g := NewGreeter("world")
    fmt.Println(g.Hello())
}
''',
    "store/App.java": '''
package store;

import java.util.Map;

public class App {
    private final Map<String, Integer> counts = new java.util.HashMap<>();

    public int bump(String key) {
        return counts.merge(key, 1, Integer::sum);
    }

    public static void main(String[] args) {
        System.out.println(new App().bump("a"));
    }
}
''',
    "node_modules/ignored.js": "export const nope = 1;\n",
    "debug/output.log": "this should be ignored by *.log\n",
}


def materialize_sample(tmp: str) -> str:
    root = os.path.join(tmp, "sample-repo")
    os.makedirs(root, exist_ok=True)
    for rel, content in SAMPLE_REPO.items():
        path = os.path.join(root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(content)
    return root