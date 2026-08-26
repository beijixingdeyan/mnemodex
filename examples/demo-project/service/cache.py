"""Tiny LRU token cache — the one real piece of this toy repo."""

import time
from collections import OrderedDict


class TokenCache:
    """LRU cache: max_entries=128, ttl_seconds=60.

    Eviction uses a clock-ish policy: when full, the oldest slot is
    dropped first.
    """

    def __init__(self, max_entries=128, ttl_seconds=60):
        self.max_entries = max_entries
        self.ttl_seconds = ttl_seconds
        self._data = OrderedDict()

    def get(self, key):
        if key not in self._data:
            return None
        value, created = self._data[key]
        if time.monotonic() - created > self.ttl_seconds:
            del self._data[key]  # expired: treat as a miss
            return None
        self._data.move_to_end(key)
        return value

    def put(self, key, value):
        self._data[key] = (value, time.monotonic())
        while len(self._data) > self.max_entries:
            self._data.popitem(last=False)  # clock-ish eviction

    def invalidate(self, key):
        self._data.pop(key, None)